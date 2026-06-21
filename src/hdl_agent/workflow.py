from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.skill_retriever.models import QueryPlan
from src.skill_retriever.tools import retrieve_rtl_skills
from src.utils.llm import ChatClient, OpenAICompatibleLLM


DEFAULT_SKILLS_ROOT = Path("skills")
DEFAULT_OUTPUT = Path("work/generated/agent_rtl.v")
DEFAULT_MAX_RETRIES = 3


@dataclass(frozen=True)
class SkillContext:
    name: str
    path: Path
    module_info: dict[str, Any]
    readme: str
    template: str


@dataclass(frozen=True)
class HDLAgentResult:
    user_request: str
    query_plan: QueryPlan
    retrieved: dict[str, Any]
    selected_skill: SkillContext
    hdl_code: str
    output_path: Path
    syntax_log: str
    repair_attempts: int


def build_query_plan(user_request: str, llm: ChatClient) -> QueryPlan:
    payload = llm.complete_json(
        [
            {
                "role": "system",
                "content": (
                    "You convert natural-language HDL programming requests into query_plan.json. "
                    "Return only a JSON object with exactly these fields: intent, positive_terms, "
                    "negative_terms, likely_categories, likely_interfaces, required_features. "
                    "Use short Verilog/RTL retrieval terms. Do not select a final skill."
                ),
            },
            {"role": "user", "content": user_request},
        ],
        temperature=0.0,
    )
    return QueryPlan.from_dict(payload)


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
    module_info_path = skill_path / "module_info.json"
    readme_path = skill_path / "README.md"
    template_path = skill_path / "template.v"
    missing = [path for path in (module_info_path, readme_path, template_path) if not path.exists()]
    if missing:
        raise RuntimeError(f"selected skill is incomplete: {', '.join(str(path) for path in missing)}")
    return SkillContext(
        name=str(result["name"]),
        path=skill_path,
        module_info=json.loads(module_info_path.read_text(encoding="utf-8")),
        readme=readme_path.read_text(encoding="utf-8"),
        template=template_path.read_text(encoding="utf-8"),
    )


def generate_hdl(user_request: str, plan: QueryPlan, skill: SkillContext, llm: ChatClient) -> str:
    content = llm.complete_text(
        [
            {
                "role": "system",
                "content": (
                    "You are an RTL generator. Produce synthesizable Verilog/SystemVerilog code only. "
                    "Use the selected skill metadata, usage guide, and template as the implementation basis. "
                    "Do not include Markdown fences or explanatory prose."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Human HDL request:\n{user_request}\n\n"
                    f"Query plan:\n{json.dumps(plan.to_dict(), indent=2)}\n\n"
                    f"Selected skill: {skill.name}\n\n"
                    f"module_info.json:\n{json.dumps(skill.module_info, indent=2)}\n\n"
                    f"README.md:\n{skill.readme}\n\n"
                    f"template.v:\n{skill.template}\n"
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
                    f"module_info.json:\n{json.dumps(skill.module_info, indent=2)}\n\n"
                    f"template.v:\n{skill.template}\n\n"
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
) -> tuple[str, str, int]:
    hdl_code = generate_hdl(user_request, plan, skill, llm)
    last_log = ""
    for attempt in range(max_retries + 1):
        check = check_hdl_syntax(hdl_code)
        last_log = check.log
        if check.ok:
            return hdl_code, last_log, attempt
        if attempt == max_retries:
            break
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


def run_hdl_agent(
    user_request: str,
    *,
    llm: ChatClient | None = None,
    skills_root: Path = DEFAULT_SKILLS_ROOT,
    output_path: Path = DEFAULT_OUTPUT,
    limit: int = 3,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> HDLAgentResult:
    active_llm = llm or OpenAICompatibleLLM()
    plan = build_query_plan(user_request, active_llm)
    retrieved = call_skill_retriever_tool(plan, skills_root, limit)
    results = retrieved.get("results", [])
    if not results:
        raise RuntimeError("skill retriever returned no results")
    selected_skill = load_skill_context(results[0])
    hdl_code, syntax_log, repair_attempts = generate_verified_hdl(
        user_request,
        plan,
        selected_skill,
        active_llm,
        max_retries=max_retries,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(hdl_code, encoding="utf-8")
    return HDLAgentResult(
        user_request=user_request,
        query_plan=plan,
        retrieved=retrieved,
        selected_skill=selected_skill,
        hdl_code=hdl_code,
        output_path=output_path,
        syntax_log=syntax_log,
        repair_attempts=repair_attempts,
    )
