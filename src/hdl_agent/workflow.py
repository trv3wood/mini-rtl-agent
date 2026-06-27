from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.cpp_model_gen.build import build_cpp_reference, run_cpp_reference_tests, write_report
from src.cpp_model_gen.codegen import generate_cpp_files
from src.cpp_model_gen.model_plan import (
    generate_cpp_model_plan,
    has_blocking_cpp_model_issue,
    write_cpp_model_plan,
)
from src.hdl_agent.final_ip_context import (
    build_final_ip_context,
    extract_final_rtl_facts,
    write_final_ip_context,
)
from src.hdl_agent.skill_selection import SkillSelectionDecision, select_skill_from_candidates
from src.skill_retriever.models import QueryPlan
from src.skill_retriever.planner import build_query_plan
from src.skill_retriever.tools import retrieve_rtl_skills
from src.spec_generator.engineer_spec import generate_engineer_spec, write_engineer_spec
from src.utils.llm import ChatClient, OpenAICompatibleLLM


DEFAULT_SKILLS_ROOT = Path("skills")
DEFAULT_OUTPUT = Path("work/generated/agent_rtl.v")
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRIEVER_LIMIT = 8
LogFn = Callable[[str], None]


@dataclass(frozen=True)
class SkillContext:
    name: str
    path: Path
    skill: dict[str, Any]
    compact_card: dict[str, Any]
    rtl_source: str


@dataclass(frozen=True)
class HDLAgentResult:
    user_request: str
    query_plan: QueryPlan
    retrieved: dict[str, Any]
    selected_skill: SkillContext
    skill_selection: SkillSelectionDecision
    hdl_code: str
    output_path: Path
    syntax_log: str
    repair_attempts: int
    artifact_paths: dict[str, Path]


def call_skill_retriever_tool(plan: QueryPlan, skills_root: Path, limit: int) -> dict[str, Any]:
    tool_input = {
        **plan.to_dict(),
        "skills_root": str(skills_root),
        "limit": limit,
    }
    if hasattr(retrieve_rtl_skills, "invoke"):
        return retrieve_rtl_skills.invoke(tool_input)
    return retrieve_rtl_skills(**tool_input)


def load_skill_context(result: dict[str, Any]) -> SkillContext:
    skill_path = Path(result["path"])
    skill_json_path = skill_path / "skill.json"
    compact_card_path = skill_path / "compact_card.json"
    missing = [path for path in (skill_json_path, compact_card_path) if not path.exists()]
    if missing:
        raise RuntimeError(f"selected skill is incomplete: {', '.join(str(path) for path in missing)}")
    skill_json = json.loads(skill_json_path.read_text(encoding="utf-8"))
    rtl_files = [str(item) for item in skill_json.get("rtl_files", [])]
    rtl_path = next((skill_path / item for item in rtl_files if (skill_path / item).exists()), None)
    if rtl_path is None:
        raise RuntimeError(f"selected skill has no readable RTL file: {skill_json_path}")
    return SkillContext(
        name=str(result["name"]),
        path=skill_path,
        skill=skill_json,
        compact_card=json.loads(compact_card_path.read_text(encoding="utf-8")),
        rtl_source=rtl_path.read_text(encoding="utf-8"),
    )


def enrich_candidate_with_compact_card(result: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(result)
    compact_card_path = Path(str(result["path"])) / "compact_card.json"
    if compact_card_path.exists():
        enriched["compact_card"] = json.loads(compact_card_path.read_text(encoding="utf-8"))
    else:
        enriched["compact_card"] = {}
    return enriched


def generate_hdl(user_request: str, plan: QueryPlan, skill: SkillContext, llm: ChatClient) -> str:
    content = llm.complete_text(
        [
            {
                "role": "system",
                "content": (
                    "You are an RTL generator. Produce synthesizable Verilog/SystemVerilog code only. "
                    "Use the selected skill JSON, compact retrieval card, and RTL source as the implementation basis. "
                    "Do not include Markdown fences or explanatory prose."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Human HDL request:\n{user_request}\n\n"
                    f"Query plan:\n{json.dumps(plan.to_dict(), indent=2)}\n\n"
                    f"Selected skill: {skill.name}\n\n"
                    f"skill.json:\n{json.dumps(skill.skill, indent=2)}\n\n"
                    f"compact_card.json:\n{json.dumps(skill.compact_card, indent=2)}\n\n"
                    f"RTL source:\n{skill.rtl_source}\n"
                ),
            },
        ],
        temperature=0.1,
    )
    return strip_markdown_fences(content)


def repair_hdl(
    user_request: str,
    plan: QueryPlan,
    skill: SkillContext,
    broken_hdl: str,
    syntax_log: str,
    llm: ChatClient,
) -> str:
    content = llm.complete_text(
        [
            {
                "role": "system",
                "content": (
                    "You repair RTL code after an iverilog syntax/compile failure. "
                    "Return corrected synthesizable Verilog/SystemVerilog code only. "
                    "Do not include Markdown fences or explanatory prose."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Human HDL request:\n{user_request}\n\n"
                    f"Query plan:\n{json.dumps(plan.to_dict(), indent=2)}\n\n"
                    f"Selected skill: {skill.name}\n\n"
                    f"skill.json:\n{json.dumps(skill.skill, indent=2)}\n\n"
                    f"compact_card.json:\n{json.dumps(skill.compact_card, indent=2)}\n\n"
                    f"RTL source:\n{skill.rtl_source}\n\n"
                    f"iverilog failure log:\n{syntax_log}\n\n"
                    f"Broken HDL:\n{broken_hdl}\n"
                ),
            },
        ],
        temperature=0.1,
    )
    return strip_markdown_fences(content)


@dataclass(frozen=True)
class SyntaxCheck:
    ok: bool
    log: str


def check_hdl_syntax(hdl_code: str, *, module_name: str = "agent_rtl") -> SyntaxCheck:
    iverilog = shutil.which("iverilog")
    if not iverilog:
        raise RuntimeError("missing required syntax checker: iverilog is not on PATH")
    with tempfile.TemporaryDirectory(prefix="hdl_agent_", dir="/tmp") as tmpdir:
        rtl_path = Path(tmpdir) / f"{module_name}.v"
        out_path = Path(tmpdir) / f"{module_name}.vvp"
        rtl_path.write_text(hdl_code, encoding="utf-8")
        run = subprocess.run(
            [iverilog, "-g2012", "-Wall", "-o", str(out_path), str(rtl_path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
    log = run.stdout.strip()
    return SyntaxCheck(ok=run.returncode == 0, log=log)


def generate_verified_hdl(
    user_request: str,
    plan: QueryPlan,
    skill: SkillContext,
    llm: ChatClient,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    log: LogFn | None = None,
) -> tuple[str, str, int]:
    emit = log or (lambda _message: None)
    emit(f"[hdl-agent] generating RTL from selected skill: {skill.name}")
    hdl_code = generate_hdl(user_request, plan, skill, llm)
    last_log = ""
    for attempt in range(max_retries + 1):
        emit(f"[hdl-agent] running iverilog syntax check: attempt {attempt + 1}/{max_retries + 1}")
        check = check_hdl_syntax(hdl_code)
        last_log = check.log
        if check.ok:
            emit(f"[hdl-agent] syntax check passed: repair_attempts={attempt}")
            return hdl_code, last_log, attempt
        if attempt == max_retries:
            break
        emit(f"[hdl-agent] syntax check failed; asking LLM to repair RTL: {summarize_log(check.log)}")
        hdl_code = repair_hdl(user_request, plan, skill, hdl_code, check.log, llm)
    raise RuntimeError(
        f"generated HDL failed iverilog syntax check after {max_retries} repair attempt(s):\n{last_log}"
    )


def strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped + "\n"
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip() + "\n"


def summarize_log(log: str, *, max_chars: int = 240) -> str:
    compact = " ".join(line.strip() for line in log.splitlines() if line.strip())
    if not compact:
        return "<no compiler output>"
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3] + "..."


def run_hdl_agent(
    user_request: str,
    *,
    llm: ChatClient | None = None,
    skills_root: Path = DEFAULT_SKILLS_ROOT,
    output_path: Path = DEFAULT_OUTPUT,
    output_dir: Path | None = None,
    limit: int = DEFAULT_RETRIEVER_LIMIT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    emit_spec: bool = False,
    emit_cpp_ref: bool = False,
    build_cpp_ref: bool = False,
    run_cpp_ref_tests: bool = False,
    allow_unsafe_cpp_gen: bool = False,
    log: LogFn | None = None,
) -> HDLAgentResult:
    emit = log or (lambda _message: None)
    emit("[hdl-agent] starting HDL generation workflow")
    if emit_cpp_ref:
        emit_spec = True
    if build_cpp_ref:
        emit_cpp_ref = True
        emit_spec = True
    if run_cpp_ref_tests:
        build_cpp_ref = True
        emit_cpp_ref = True
        emit_spec = True
    emit(f"[hdl-agent] skills_root={skills_root} output={output_dir or output_path} limit={limit}")
    active_llm = llm or OpenAICompatibleLLM()
    emit("[hdl-agent] building query_plan from user request")
    plan = build_query_plan(user_request, active_llm)
    emit(
        "[hdl-agent] query_plan ready: "
        f"intent={plan.intent!r} positive_terms={plan.positive_terms}"
    )
    query_plan_path: Path | None = None
    retrieval_trace_path: Path | None = None
    reports_dir: Path | None = None
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        reports_dir = output_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        query_plan_path = output_dir / "query_plan.json"
        query_plan_path.write_text(json.dumps(plan.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        emit(f"[plan] wrote {query_plan_path}")
    emit("[hdl-agent] invoking skill retriever tool")
    retrieved = call_skill_retriever_tool(plan, skills_root, limit)
    results = retrieved.get("results", [])
    if not results:
        raise RuntimeError("skill retriever returned no results")
    enriched_results = [enrich_candidate_with_compact_card(item) for item in results]
    selection = select_skill_from_candidates(
        user_request=user_request,
        query_plan=plan,
        candidates=enriched_results,
        llm=active_llm,
    )
    retrieved["skill_selection"] = {
        "selected_skill": selection.selected_skill,
        "selected_rank": selection.selected_rank,
        "confidence": selection.confidence,
        "reason": selection.reason,
        "rejected": selection.rejected,
    }
    if output_dir is not None:
        retrieval_trace_path = output_dir / "retrieval_trace.json"
        retrieval_trace_path.write_text(json.dumps(retrieved, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        emit(f"[retriever] wrote {retrieval_trace_path}")
    ranked = ", ".join(f"{item['name']}({item['score']})" for item in results[: min(5, len(results))])
    emit(f"[hdl-agent] retrieved {len(results)} skill candidate(s): {ranked}")
    selected_result = enriched_results[selection.selected_rank - 1]
    selected_skill = load_skill_context(selected_result)
    emit(
        "[selector] selected "
        f"{selected_skill.path} rank={selection.selected_rank} confidence={selection.confidence}: {selection.reason}"
    )
    try:
        hdl_code, syntax_log, repair_attempts = generate_verified_hdl(
            user_request,
            plan,
            selected_skill,
            active_llm,
            max_retries=max_retries,
            log=emit,
        )
    except RuntimeError as exc:
        if output_dir is not None and reports_dir is not None:
            write_report(
                {
                    "status": "failed",
                    "command": ["iverilog", "-g2012", "-Wall"],
                    "returncode": 1,
                    "stdout": "",
                    "stderr": str(exc),
                },
                reports_dir / "iverilog_check.json",
            )
        raise
    artifact_paths: dict[str, Path] = {}
    if output_dir is not None:
        tmp_rtl = output_dir / "_final_rtl.v"
        tmp_rtl.write_text(hdl_code, encoding="utf-8")
        facts = extract_final_rtl_facts(tmp_rtl, syntax_check_status="passed")
        output_path = output_dir / f"{facts.module_name}.v"
        if output_path != tmp_rtl:
            output_path.write_text(hdl_code, encoding="utf-8")
            tmp_rtl.unlink(missing_ok=True)
        facts = extract_final_rtl_facts(output_path, syntax_check_status="passed")
        artifact_paths["rtl"] = output_path
        emit(f"[hdl] wrote {output_path}")
        if reports_dir is not None:
            artifact_paths["iverilog_check"] = write_report(
                {
                    "status": "passed",
                    "command": ["iverilog", "-g2012", "-Wall"],
                    "returncode": 0,
                    "stdout": syntax_log,
                    "stderr": "",
                    "repair_attempts": repair_attempts,
                },
                reports_dir / "iverilog_check.json",
            )
            emit("[check] iverilog passed")
        if emit_spec:
            selected_skill_record = {
                "skill_id": selected_skill.name,
                "skill_dir": str(selected_skill.path),
                "score": selected_result.get("score", 0),
                "name": selected_skill.name,
                "compact_card": selected_skill.compact_card,
            }
            final_context = build_final_ip_context(
                request=user_request,
                selected_skill=selected_skill_record,
                final_rtl_facts=facts,
                output_dir=output_dir,
                query_plan_path=query_plan_path,
                retrieval_trace_path=retrieval_trace_path,
            )
            context_path = write_final_ip_context(final_context, output_dir / "final_ip_context.json")
            artifact_paths["final_ip_context"] = context_path
            emit(f"[context] wrote {context_path}")
            engineer_spec = generate_engineer_spec(llm_client=active_llm, final_ip_context=final_context)
            spec_path = write_engineer_spec(engineer_spec, output_dir / "engineer_spec.json")
            artifact_paths["engineer_spec"] = spec_path
            emit(f"[spec] wrote {spec_path}")
            if emit_cpp_ref:
                cpp_model = generate_cpp_model_plan(
                    llm_client=active_llm,
                    final_ip_context=final_context,
                    engineer_spec=engineer_spec,
                )
                cpp_model_path = write_cpp_model_plan(cpp_model, output_dir / "cpp_model.json")
                artifact_paths["cpp_model"] = cpp_model_path
                emit(f"[cpp-plan] wrote {cpp_model_path}")
                blocking = has_blocking_cpp_model_issue(cpp_model)
                if blocking and not allow_unsafe_cpp_gen:
                    reason_report = {
                        "status": "skipped",
                        "reason": "blocking_unknown_or_conflict",
                        "command": [],
                        "returncode": None,
                        "stdout": "",
                        "stderr": "",
                        "details": cpp_model.get("behavior_contract", {}).get("unknowns", []),
                    }
                    if reports_dir is not None:
                        artifact_paths["cpp_build"] = write_report(reason_report, reports_dir / "cpp_build.json")
                        artifact_paths["cpp_test"] = write_report(reason_report, reports_dir / "cpp_test.json")
                    emit("[cpp-codegen] skipped: blocking unknown/conflict in cpp_model.json")
                else:
                    cpp_dir = output_dir / "cpp"
                    cpp_files = generate_cpp_files(
                        llm_client=active_llm,
                        cpp_model_plan=cpp_model,
                        engineer_spec=engineer_spec,
                        output_cpp_dir=cpp_dir,
                    )
                    for path in cpp_files:
                        emit(f"[cpp-codegen] wrote {path}")
                    artifact_paths["cpp_dir"] = cpp_dir
                    if build_cpp_ref:
                        build_report = build_cpp_reference(cpp_dir=cpp_dir)
                        if reports_dir is not None:
                            artifact_paths["cpp_build"] = write_report(build_report, reports_dir / "cpp_build.json")
                        emit(f"[cpp-build] {build_report['status']}")
                        if build_report["status"] != "passed":
                            raise RuntimeError(f"C++ reference model build failed:\n{build_report.get('stderr', '')}")
                    if run_cpp_ref_tests:
                        test_report = run_cpp_reference_tests(cpp_dir=cpp_dir)
                        if reports_dir is not None:
                            artifact_paths["cpp_test"] = write_report(test_report, reports_dir / "cpp_test.json")
                        emit(f"[cpp-test] {test_report['status']}")
                        if test_report["status"] != "passed":
                            raise RuntimeError(f"C++ reference model tests failed:\n{test_report.get('stderr', '')}")
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(hdl_code, encoding="utf-8")
        artifact_paths["rtl"] = output_path
        emit(f"[hdl-agent] wrote generated RTL: {output_path}")
    return HDLAgentResult(
        user_request=user_request,
        query_plan=plan,
        retrieved=retrieved,
        selected_skill=selected_skill,
        skill_selection=selection,
        hdl_code=hdl_code,
        output_path=output_path,
        syntax_log=syntax_log,
        repair_attempts=repair_attempts,
        artifact_paths=artifact_paths,
    )
