from __future__ import annotations

import json
import hashlib
from dataclasses import asdict, replace
from datetime import datetime, timezone
import shutil
import subprocess
from pathlib import Path

from src.utils.llm import ChatClient, OpenAICompatibleLLM

from .classifier import classify
from .frontend import get_last_parse_warnings, parse_project
from .generator import (
    BUILDER_VERSION,
    generate_instantiation,
    generate_readme,
    generate_template,
    generate_testbench,
    module_info_json,
    sanitize_skill_name,
    score_skill,
)
from .hierarchy import build_module_hierarchy
from .hierarchy import build_skill_candidates
from .hierarchy import mermaid_dependency_graph
from .hierarchy import module_dependency_graph
from .models import ModuleIR, ModuleInfo, SkillCandidate, SourceLocation, VerificationResult
from .scanner import scan_rtl_files
from .schema import validate_module_info
from .spec_generator import generate_skill_spec
from .verifier import verify_candidate


class SkillBuilderError(RuntimeError):
    pass


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def atomic_write_json(path: Path, data: dict) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def relative_to_repo(path: str, repo_path: Path) -> str:
    source = Path(path).resolve()
    try:
        return source.relative_to(repo_path).as_posix()
    except ValueError:
        return source.name


def packaged_rtl_path(source_file: str, repo_path: Path) -> str:
    relative = relative_to_repo(source_file, repo_path)
    if relative.startswith("rtl/"):
        relative = relative.removeprefix("rtl/")
    return f"rtl/{relative}"


def source_location_json(source: SourceLocation | None, repo_path: Path) -> dict | None:
    if source is None:
        return None
    return {
        "file": relative_to_repo(source.file, repo_path),
        "line_start": source.line_start,
        "line_end": source.line_end,
    }


def git_commit(repo_path: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    if completed.returncode != 0:
        return "unknown"
    return completed.stdout.strip() or "unknown"


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_candidate_sources(candidate: SkillCandidate, skill_dir: Path, repo_path: Path) -> list[str]:
    packaged_paths = []
    for source_file in candidate.source_files:
        source = Path(source_file)
        relative = packaged_rtl_path(source_file, repo_path).removeprefix("rtl/")
        destination = skill_dir / "rtl" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        packaged_paths.append(destination.as_posix())
    return packaged_paths


def verification_stage_summary(verification: VerificationResult) -> dict:
    return {
        "source_compile": verification.source_compile.status,
        "generated_tb_compile": verification.generated_tb_compile.status,
        "simulation": verification.simulation.status,
        "failure_stage": verification.failure_stage,
        "failure_category": verification.failure_category,
    }


def quality_tier(candidate: SkillCandidate, schema_ok: bool, verification: VerificationResult) -> str:
    if not candidate.root_source or candidate.candidate_kind == "unresolved":
        return "rejected"
    if any("duplicate module definition" in warning for warning in candidate.hierarchy_warnings):
        return "rejected"
    if not schema_ok:
        return "bronze"
    if verification.source_compile.status != "passed":
        return "bronze"
    if not candidate.is_self_contained:
        return "bronze"
    if verification.generated_tb_compile.status == "passed" and verification.simulation.status == "passed":
        return "gold_candidate"
    return "silver"


def status_gate(
    name: str,
    status: str,
    *,
    evidence_path: str,
    blocking_for_quality: bool,
    reason: str = "",
) -> dict:
    passed = status == "passed"
    return {
        "name": name,
        "status": status,
        "passed": passed,
        "blocking_for_quality": blocking_for_quality,
        "evidence_path": evidence_path,
        "reason": reason,
    }


def compact_gate_reason(text: str, limit: int = 240) -> str:
    compacted = " ".join(text.split())
    if len(compacted) <= limit:
        return compacted
    return compacted[: limit - 3].rstrip() + "..."


def quality_gates_json(candidate: SkillCandidate, schema_ok: bool, verification: VerificationResult) -> dict:
    duplicate_definition = any(
        "duplicate module definition" in warning for warning in candidate.hierarchy_warnings
    )
    gates = [
        status_gate(
            "metadata_schema",
            "passed" if schema_ok else "failed",
            evidence_path="module_info.json",
            blocking_for_quality=True,
            reason="" if schema_ok else "module_info.json failed schema validation",
        ),
        status_gate(
            "dependency_closure",
            "passed" if candidate.is_self_contained else "failed",
            evidence_path="closure.json",
            blocking_for_quality=True,
            reason=(
                "closure is self-contained"
                if candidate.is_self_contained
                else "unresolved dependencies, duplicate definitions, or missing root source"
            ),
        ),
        status_gate(
            "duplicate_definition",
            "failed" if duplicate_definition else "passed",
            evidence_path="closure.json",
            blocking_for_quality=True,
            reason="duplicate module definition detected" if duplicate_definition else "",
        ),
        status_gate(
            "source_compile",
            verification.source_compile.status,
            evidence_path="tool_runs/source_compile.json",
            blocking_for_quality=True,
            reason=compact_gate_reason(verification.source_compile.stderr or verification.source_compile.stdout),
        ),
        status_gate(
            "generated_tb_compile",
            verification.generated_tb_compile.status,
            evidence_path="tool_runs/tb_compile.json",
            blocking_for_quality=False,
            reason=compact_gate_reason(
                verification.generated_tb_compile.stderr or verification.generated_tb_compile.stdout
            ),
        ),
        status_gate(
            "smoke_simulation",
            verification.simulation.status,
            evidence_path="tool_runs/simulation.json",
            blocking_for_quality=False,
            reason=compact_gate_reason(verification.simulation.stderr or verification.simulation.stdout),
        ),
        status_gate(
            "original_tests",
            "absent",
            evidence_path="tests/original/README.md",
            blocking_for_quality=False,
            reason="original repository tests are not imported yet",
        ),
        status_gate(
            "formal_verification",
            "absent",
            evidence_path="quality.json",
            blocking_for_quality=False,
            reason="formal checks are not implemented yet",
        ),
        status_gate(
            "manual_review",
            "absent",
            evidence_path="quality.json",
            blocking_for_quality=False,
            reason="manual review is not recorded by the builder",
        ),
    ]
    summary: dict[str, int] = {}
    for gate in gates:
        summary[gate["status"]] = summary.get(gate["status"], 0) + 1
    return {
        "schema_version": "0.1",
        "gates": gates,
        "summary": summary,
    }


def manifest_json(candidate: SkillCandidate, repo_path: Path) -> dict:
    return {
        "skill_id": candidate.skill_id,
        "root_module": candidate.root_module,
        "root_source": packaged_rtl_path(candidate.root_source, repo_path) if candidate.root_source else "",
        "candidate_kind": candidate.candidate_kind,
        "dependency_modules": candidate.dependency_modules,
        "source_files": [packaged_rtl_path(source_file, repo_path) for source_file in candidate.source_files],
        "unresolved_dependencies": candidate.unresolved_dependencies,
        "external_dependencies": candidate.external_dependencies,
        "vendor_primitives": candidate.vendor_primitives,
        "is_self_contained": candidate.is_self_contained,
        "closure_manifest": "closure.json",
        "generated_smoke_test": "tests/generated/generated_smoke_tb.v",
        "original_tests": [],
    }


def closure_json(
    candidate: SkillCandidate,
    repo_path: Path,
    skill_dir: Path,
    packaged_source_files: list[str],
    verification: VerificationResult,
) -> dict:
    packaged_relative = []
    for source_file in packaged_source_files:
        path = Path(source_file)
        try:
            packaged_relative.append(path.relative_to(skill_dir).as_posix())
        except ValueError:
            packaged_relative.append(path.as_posix())
    packaged_to_original = {
        packaged_rtl_path(source_file, repo_path): relative_to_repo(source_file, repo_path)
        for source_file in candidate.source_files
    }
    return {
        "schema_version": "0.1",
        "skill_id": candidate.skill_id,
        "root_module": candidate.root_module,
        "candidate_kind": candidate.candidate_kind,
        "dependency_completeness": "complete" if candidate.is_self_contained else "incomplete",
        "root_source": packaged_rtl_path(candidate.root_source, repo_path) if candidate.root_source else "",
        "dependency_modules": candidate.dependency_modules,
        "rtl_files": {
            "packaged": sorted(packaged_relative),
            "original_to_packaged": {
                relative_to_repo(original, repo_path): packaged_rtl_path(original, repo_path)
                for original in candidate.source_files
            },
            "packaged_to_original": packaged_to_original,
        },
        "unresolved_dependencies": candidate.unresolved_dependencies,
        "external_dependencies": candidate.external_dependencies,
        "vendor_primitives": candidate.vendor_primitives,
        "dependency_issues": [asdict(issue) for issue in candidate.dependency_issues],
        "hierarchy_warnings": candidate.hierarchy_warnings,
        "verification_boundary": {
            "source_compile": verification.source_compile.status,
            "generated_tb_compile": verification.generated_tb_compile.status,
            "smoke_simulation": verification.simulation.status,
            "original_tests": "absent",
            "formal_verification": "absent",
            "manual_review": "absent",
        },
    }


def quality_json(
    candidate: SkillCandidate,
    module: ModuleInfo,
    schema_ok: bool,
    verification: VerificationResult,
    tier: str,
) -> dict:
    quality_gates = quality_gates_json(candidate, schema_ok, verification)
    return {
        "frontend": {
            "backends": candidate.frontend_backends,
            "instance_backends": candidate.frontend_instance_backends,
            "warnings": sorted(set(candidate.frontend_warnings + candidate.hierarchy_warnings)),
        },
        "hierarchy": {
            "closure_status": "complete" if candidate.is_self_contained else "incomplete",
            "dependency_count": len(candidate.dependency_modules),
            "unresolved_count": len(candidate.unresolved_dependencies),
            "dependency_issues": [asdict(issue) for issue in candidate.dependency_issues],
        },
        "verification": {
            **verification_stage_summary(verification),
            "source_compile_detail": asdict(verification.source_compile),
            "generated_tb_compile_detail": asdict(verification.generated_tb_compile),
            "simulation_detail": asdict(verification.simulation),
            "original_tests": {"status": "absent", "reason": "original repository tests are not imported yet"},
            "formal_verification": {"status": "absent"},
            "manual_review": {"status": "absent"},
        },
        "schema_ok": schema_ok,
        "quality_tier": tier,
        "quality_gates": quality_gates,
    }


def provenance_json(candidate: SkillCandidate, repo_path: Path) -> dict:
    return {
        "schema_version": "0.1",
        "repository": str(repo_path),
        "commit": git_commit(repo_path),
        "license": "unknown",
        "root_module": candidate.root_module,
        "root_source": packaged_rtl_path(candidate.root_source, repo_path) if candidate.root_source else "",
        "source_hashes": {
            packaged_rtl_path(source_file, repo_path): sha256_file(source_file)
            for source_file in candidate.source_files
            if Path(source_file).exists()
        },
        "extractor_version": BUILDER_VERSION,
        "schema_generator": "mini-rtl-agent.skill_builder",
        "generation_model": "unknown",
        "generation_time": datetime.now(timezone.utc).isoformat(),
    }


def adaptation_json(module: ModuleInfo, candidate: SkillCandidate) -> dict:
    return {
        "schema_version": "0.1",
        "root_module": candidate.root_module,
        "customizable_parameters": [
            {
                "name": parameter.name,
                "default": parameter.default or "unspecified",
                "risk": "requires source compile and smoke simulation after change",
            }
            for parameter in module.parameters
        ],
        "interface_ports": [
            {
                "name": port.name,
                "direction": port.direction,
                "width": port.width,
                "risk": "interface changes require downstream instantiation and testbench updates",
            }
            for port in module.ports
        ],
        "allowed_variants": [],
        "modification_risks": [
            "The generated template is not a behavioral clone of the source RTL.",
            "Parameter and port changes must be recompiled with the full dependency closure.",
        ],
        "revalidation_required": [
            "source_compile",
            "generated_tb_compile",
            "smoke_simulation",
        ],
        "do_not_modify_without_review": [
            "clock and reset semantics",
            "module dependency boundary",
            "protocol-visible handshake or valid/ready behavior",
        ],
    }


def evidence_pack_json(
    module_ir: ModuleIR,
    candidate: SkillCandidate,
    repo_path: Path,
    verification: VerificationResult,
) -> dict:
    evidence: list[dict] = []

    def add(prefix: str, evidence_type: str, payload: dict) -> dict:
        item = {
            "id": f"{prefix}_{len([entry for entry in evidence if entry['id'].startswith(prefix)]) + 1:03d}",
            "type": evidence_type,
            "status": "observed",
            **payload,
        }
        evidence.append(item)
        return item

    ports = [
        add(
            "E_PORT",
            "port",
            {
                "name": port.name,
                "direction": port.direction,
                "width": port.width,
                "data_type": port.data_type,
                "source": source_location_json(port.source, repo_path),
                "backend": module_ir.port_backend,
            },
        )
        for port in module_ir.ports
    ]
    parameters = [
        add(
            "E_PARAM",
            "parameter",
            {
                "name": parameter.name,
                "default": parameter.default,
                "kind": parameter.kind,
                "source": source_location_json(parameter.source, repo_path),
                "backend": module_ir.parameter_backend,
            },
        )
        for parameter in module_ir.parameters
    ]
    instances = [
        add(
            "E_INST",
            "module_instance",
            {
                "module_name": instance.module_name,
                "instance_name": instance.instance_name,
                "parameter_overrides": instance.parameter_overrides,
                "port_connections": instance.port_connections,
                "source": source_location_json(instance.source, repo_path),
                "backend": module_ir.instance_backend,
            },
        )
        for instance in module_ir.instances
    ]
    clock_candidates = [
        add("E_CLOCK", "clock_candidate", {"value": clock, "backend": module_ir.port_backend})
        for clock in module_ir.clock_candidates
    ]
    reset_candidates = [
        add("E_RESET", "reset_candidate", {"value": reset, "backend": module_ir.port_backend})
        for reset in module_ir.reset_candidates
    ]
    fsm_candidates = [
        add("E_FSM", "fsm_candidate", {"value": state, "backend": module_ir.parse_backend})
        for state in module_ir.states
    ]
    memory_candidates = [
        add(
            "E_MEM",
            "memory_candidate",
            {
                "name": fact.name,
                "expression": fact.expression,
                "source": source_location_json(fact.source, repo_path),
                "backend": fact.backend,
            },
        )
        for fact in module_ir.memory_candidates
    ]
    always_blocks = [
        add(
            "E_ALWAYS",
            "always_block",
            {
                "name": fact.name,
                "sensitivity": fact.expression,
                "source": source_location_json(fact.source, repo_path),
                "backend": fact.backend,
            },
        )
        for fact in module_ir.always_blocks
    ]
    continuous_assignments = [
        add(
            "E_ASSIGN",
            "continuous_assignment",
            {
                "name": fact.name,
                "expression": fact.expression,
                "source": source_location_json(fact.source, repo_path),
                "backend": fact.backend,
            },
        )
        for fact in module_ir.continuous_assignments
    ]
    assertions = [
        add(
            "E_ASSERT",
            "assertion",
            {
                "name": fact.name,
                "kind": fact.kind,
                "expression": fact.expression,
                "source": source_location_json(fact.source, repo_path),
                "backend": fact.backend,
            },
        )
        for fact in module_ir.assertions
    ]
    comments = [
        add("E_COMMENT", "comment", {"value": comment, "backend": module_ir.parse_backend})
        for comment in module_ir.comments
    ]
    verification_evidence = [
        add(
            "E_VERIFY",
            "verification_stage",
            {
                "stage": "source_compile",
                "result": verification.source_compile.status,
                "status": "validated" if verification.source_compile.status == "passed" else "unknown",
                "backend": "iverilog",
                "tool_run": "tool_runs/source_compile.json",
            },
        ),
        add(
            "E_VERIFY",
            "verification_stage",
            {
                "stage": "generated_tb_compile",
                "result": verification.generated_tb_compile.status,
                "status": "validated" if verification.generated_tb_compile.status == "passed" else "unknown",
                "backend": "iverilog",
                "tool_run": "tool_runs/tb_compile.json",
            },
        ),
        add(
            "E_VERIFY",
            "verification_stage",
            {
                "stage": "smoke_simulation",
                "result": verification.simulation.status,
                "status": "validated" if verification.simulation.status == "passed" else "unknown",
                "backend": "vvp",
                "tool_run": "tool_runs/simulation.json",
            },
        ),
    ]

    return {
        "schema_version": "0.1",
        "module": module_ir.name,
        "root_source": packaged_rtl_path(candidate.root_source, repo_path) if candidate.root_source else "",
        "dependency_modules": candidate.dependency_modules,
        "ports": ports,
        "parameters": parameters,
        "instances": instances,
        "clock_candidates": clock_candidates,
        "reset_candidates": reset_candidates,
        "fsm_candidates": fsm_candidates,
        "memory_candidates": memory_candidates,
        "always_blocks": always_blocks,
        "continuous_assignments": continuous_assignments,
        "assertions": assertions,
        "comments": comments,
        "verification_stages": verification_evidence,
        "source_compile": verification.source_compile.status,
        "source_locations": {
            module_ir.name: {
                "file": relative_to_repo(module_ir.source_file, repo_path),
                "backend": module_ir.parse_backend,
            }
        },
        "evidence": evidence,
    }


def write_tool_runs(skill_dir: Path, verification: VerificationResult, module_ir: ModuleIR) -> None:
    tool_runs_dir = skill_dir / "tool_runs"
    atomic_write_json(
        tool_runs_dir / "frontend.json",
        {
            "parse_backend": module_ir.parse_backend,
            "syntax_backend": module_ir.syntax_backend,
            "instance_backend": module_ir.instance_backend,
            "parameter_backend": module_ir.parameter_backend,
            "port_backend": module_ir.port_backend,
            "semantic_status": module_ir.semantic_status,
            "warnings": module_ir.parse_warnings,
        },
    )
    atomic_write_json(tool_runs_dir / "source_compile.json", asdict(verification.source_compile))
    atomic_write_json(tool_runs_dir / "tb_compile.json", asdict(verification.generated_tb_compile))
    atomic_write_json(tool_runs_dir / "simulation.json", asdict(verification.simulation))


def write_skill(
    module: ModuleInfo,
    module_ir: ModuleIR,
    candidate: SkillCandidate,
    output_root: Path,
    repo_path: Path,
    llm: ChatClient,
    cache_dir: Path | None = None,
) -> dict:
    skill_name = candidate.skill_id
    skill_dir = output_root / skill_name
    examples_dir = skill_dir / "examples"
    examples_dir.mkdir(parents=True, exist_ok=True)

    module_info_text = module_info_json(module)
    module_info = json.loads(module_info_text)
    schema_errors = validate_module_info(module_info)
    if schema_errors:
        raise SkillBuilderError(f"generated module_info invalid for {module.name}: {schema_errors}")

    atomic_write_text(skill_dir / "module_info.json", module_info_text)
    atomic_write_text(skill_dir / "README.md", generate_readme(module))
    atomic_write_text(skill_dir / "template.v", generate_template(module))
    atomic_write_json(skill_dir / "module_ir.json", asdict(module_ir))
    atomic_write_text(examples_dir / "instantiation.v", generate_instantiation(module))
    tb_path = examples_dir / f"tb_{module.name}.v"
    testbench_text = generate_testbench(module)
    atomic_write_text(tb_path, testbench_text)
    generated_tests_dir = skill_dir / "tests" / "generated"
    original_tests_dir = skill_dir / "tests" / "original"
    atomic_write_text(generated_tests_dir / "generated_smoke_tb.v", testbench_text)
    atomic_write_text(
        original_tests_dir / "README.md",
        "Original upstream tests are not imported by the current builder.\n",
    )
    packaged_source_files = copy_candidate_sources(candidate, skill_dir, repo_path)
    verification_candidate = replace(candidate, source_files=packaged_source_files)
    verification = verify_candidate(verification_candidate, skill_dir, tb_path)
    tier = quality_tier(candidate, not schema_errors, verification)
    quality_gates = quality_gates_json(candidate, not schema_errors, verification)
    evidence_pack = evidence_pack_json(module_ir, candidate, repo_path, verification)
    atomic_write_json(skill_dir / "manifest.json", manifest_json(candidate, repo_path))
    atomic_write_json(
        skill_dir / "closure.json",
        closure_json(candidate, repo_path, skill_dir, packaged_source_files, verification),
    )
    atomic_write_json(skill_dir / "quality.json", quality_json(candidate, module, not schema_errors, verification, tier))
    atomic_write_json(skill_dir / "evidence.json", evidence_pack)
    atomic_write_json(skill_dir / "skill_spec.json", generate_skill_spec(module, candidate, evidence_pack, verification, tier, llm, cache_dir))
    atomic_write_json(skill_dir / "provenance.json", provenance_json(candidate, repo_path))
    atomic_write_json(skill_dir / "adaptation.json", adaptation_json(module, candidate))
    write_tool_runs(skill_dir, verification, module_ir)

    files_ok = all(
        path.exists()
        for path in (
            skill_dir / "module_info.json",
            skill_dir / "README.md",
            skill_dir / "template.v",
            skill_dir / "manifest.json",
            skill_dir / "closure.json",
            skill_dir / "quality.json",
            skill_dir / "evidence.json",
            skill_dir / "skill_spec.json",
            skill_dir / "provenance.json",
            skill_dir / "adaptation.json",
            skill_dir / "module_ir.json",
            skill_dir / "tool_runs" / "frontend.json",
            skill_dir / "tool_runs" / "source_compile.json",
            skill_dir / "tool_runs" / "tb_compile.json",
            skill_dir / "tool_runs" / "simulation.json",
            examples_dir / "instantiation.v",
            examples_dir / f"tb_{module.name}.v",
            generated_tests_dir / "generated_smoke_tb.v",
            original_tests_dir / "README.md",
        )
    )
    sim_ok = verification.simulation.status == "passed"
    sim_log = "\n".join(
        part
        for part in (
            verification.source_compile.stdout,
            verification.source_compile.stderr,
            verification.generated_tb_compile.stdout,
            verification.generated_tb_compile.stderr,
            verification.simulation.stdout,
            verification.simulation.stderr,
        )
        if part
    )
    score = score_skill(module, files_ok, sim_ok)
    return {
        "name": module.name,
        "skill_name": skill_name,
        "source_path": str(module.source_path),
        "category": module.category,
        "patterns": module.patterns,
        "interfaces": module.interfaces,
        "sim_ok": sim_ok,
        "sim_log": sim_log,
        "candidate_kind": candidate.candidate_kind,
        "is_self_contained": candidate.is_self_contained,
        "dependency_modules": candidate.dependency_modules,
        "unresolved_dependencies": candidate.unresolved_dependencies,
        "vendor_primitives": candidate.vendor_primitives,
        "verification": verification_stage_summary(verification),
        "quality_tier": tier,
        "quality_gate_summary": quality_gates["summary"],
        "quality_gates": quality_gates["gates"],
        "score": {
            "total": score.total,
            "metadata_completeness": score.metadata_completeness,
            "interface_quality": score.interface_quality,
            "documentation_quality": score.documentation_quality,
            "verification_quality": score.verification_quality,
            "template_usability": score.template_usability,
            "notes": score.notes,
        },
        "schema_ok": not schema_errors,
        "schema_errors": schema_errors,
        "paths": {
            "module_info": str(skill_dir / "module_info.json"),
            "readme": str(skill_dir / "README.md"),
            "template": str(skill_dir / "template.v"),
            "manifest": str(skill_dir / "manifest.json"),
            "closure": str(skill_dir / "closure.json"),
            "quality": str(skill_dir / "quality.json"),
            "evidence": str(skill_dir / "evidence.json"),
            "skill_spec": str(skill_dir / "skill_spec.json"),
            "provenance": str(skill_dir / "provenance.json"),
            "adaptation": str(skill_dir / "adaptation.json"),
            "module_ir": str(skill_dir / "module_ir.json"),
            "tool_runs": str(skill_dir / "tool_runs"),
            "instantiation": str(examples_dir / "instantiation.v"),
            "testbench": str(examples_dir / f"tb_{module.name}.v"),
            "generated_smoke_test": str(generated_tests_dir / "generated_smoke_tb.v"),
            "original_tests": str(original_tests_dir),
        },
    }


def clean_output_root(output_root: Path) -> None:
    if not output_root.exists():
        return
    for child in output_root.iterdir():
        if child.name == ".llm_cache":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        elif child.name == "report.json":
            child.unlink()


def build_skill_library(
    repo_path: Path,
    output_root: Path | None = None,
    clean: bool = False,
    llm: ChatClient | None = None,
    candidate_mode: str = "all",
) -> dict:
    repo_path = repo_path.resolve()
    if not repo_path.exists() or not repo_path.is_dir():
        raise SkillBuilderError(f"repo_path is not a directory: {repo_path}")
    output_root = (output_root or (Path.cwd() / "work" / "built_skills")).resolve()
    if clean:
        clean_output_root(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    if candidate_mode not in {"all", "roots"}:
        raise SkillBuilderError("candidate_mode must be 'all' or 'roots'")

    rtl_files = scan_rtl_files(repo_path)
    module_irs = parse_project(rtl_files)
    hierarchy = build_module_hierarchy(module_irs)
    dependency_graph = module_dependency_graph(hierarchy)
    direct_graph_path = output_root / "dependency_graph.mmd"
    closure_graph_path = output_root / "dependency_closure_graph.mmd"
    atomic_write_text(direct_graph_path, mermaid_dependency_graph(hierarchy, closure=False))
    atomic_write_text(closure_graph_path, mermaid_dependency_graph(hierarchy, closure=True))
    candidates = build_skill_candidates(hierarchy, include_internal=candidate_mode == "all")
    modules: list[ModuleInfo] = []
    module_candidate_pairs: list[tuple[ModuleInfo, ModuleIR, SkillCandidate]] = []
    parse_warnings = get_last_parse_warnings()
    for module_ir in module_irs:
        parse_warnings.extend(module_ir.parse_warnings)
    active_llm = llm
    if candidates and active_llm is None:
        active_llm = OpenAICompatibleLLM()
    llm_cache_dir = output_root / ".llm_cache"
    module_lookup = {(module_ir.name, module_ir.source_file): module_ir for module_ir in module_irs}
    for candidate in candidates:
        module_ir = module_lookup.get((candidate.root_module, candidate.root_source))
        if module_ir is None:
            module_ir = hierarchy.modules.get(candidate.root_module)
        if module_ir is None:
            continue
        module = classify(module_ir.to_module_info(), active_llm, cache_dir=llm_cache_dir)
        modules.append(module)
        module_candidate_pairs.append((module, module_ir, candidate))

    skills = [
        write_skill(module, module_ir, candidate, output_root, repo_path, active_llm, llm_cache_dir)
        for module, module_ir, candidate in module_candidate_pairs
    ]
    backend_counts = {"pyslang": 0, "regex": 0}
    syntax_backend_counts: dict[str, int] = {}
    instance_backend_counts: dict[str, int] = {}
    for module_ir in module_irs:
        backend_counts[module_ir.parse_backend] = backend_counts.get(module_ir.parse_backend, 0) + 1
        syntax_backend_counts[module_ir.syntax_backend] = syntax_backend_counts.get(module_ir.syntax_backend, 0) + 1
        instance_backend_counts[module_ir.instance_backend] = instance_backend_counts.get(module_ir.instance_backend, 0) + 1
    candidate_counts = {kind: 0 for kind in ("standalone", "composite", "internal", "unresolved", "cyclic")}
    for candidate in candidates:
        candidate_counts[candidate.candidate_kind] = candidate_counts.get(candidate.candidate_kind, 0) + 1
    verification_counts = {
        "source_compile_passed": sum(1 for skill in skills if skill["verification"]["source_compile"] == "passed"),
        "source_compile_failed": sum(
            1 for skill in skills if skill["verification"]["source_compile"] not in {"passed", "skipped"}
        ),
        "tb_compile_passed": sum(1 for skill in skills if skill["verification"]["generated_tb_compile"] == "passed"),
        "tb_compile_failed": sum(
            1 for skill in skills if skill["verification"]["generated_tb_compile"] not in {"passed", "skipped"}
        ),
        "simulation_passed": sum(1 for skill in skills if skill["verification"]["simulation"] == "passed"),
        "simulation_failed": sum(
            1 for skill in skills if skill["verification"]["simulation"] not in {"passed", "skipped"}
        ),
        "simulation_skipped": sum(1 for skill in skills if skill["verification"]["simulation"] == "skipped"),
    }
    quality_tiers = {tier: 0 for tier in ("rejected", "bronze", "silver", "gold_candidate")}
    for skill in skills:
        quality_tiers[skill["quality_tier"]] = quality_tiers.get(skill["quality_tier"], 0) + 1
    quality_gate_counts: dict[str, dict[str, int]] = {}
    for skill in skills:
        for gate in skill.get("quality_gates", []):
            gate_counts = quality_gate_counts.setdefault(gate["name"], {})
            gate_counts[gate["status"]] = gate_counts.get(gate["status"], 0) + 1
    dependency_issues = [issue for issues in hierarchy.dependency_issues.values() for issue in issues]
    report = {
        "input_repo": str(repo_path),
        "output_root": str(output_root),
        "candidate_mode": candidate_mode,
        "rtl_files_scanned": len(rtl_files),
        "modules_extracted": len(module_irs),
        "skills_generated": len(skills),
        "llm_cache_dir": str(llm_cache_dir),
        "parse_errors": [{"warning": warning} for warning in sorted(set(parse_warnings))],
        "frontend": {
            "backend_counts": backend_counts,
            "syntax_backend_counts": syntax_backend_counts,
            "instance_backend_counts": instance_backend_counts,
            "module_count": len(module_irs),
            "root_modules": hierarchy.roots,
            "unresolved_dependencies": {
                name: sorted(dependencies)
                for name, dependencies in sorted(hierarchy.unresolved_dependencies.items())
            },
            "duplicate_modules": hierarchy.duplicate_modules,
            "parse_warnings": sorted(set(parse_warnings)),
        },
        "dependency_graph": {
            **dependency_graph,
            "mermaid_direct": str(direct_graph_path),
            "mermaid_closure": str(closure_graph_path),
        },
        "candidates": {"total": len(candidates), **candidate_counts},
        "dependencies": {
            "resolved": sum(len(candidate.dependency_modules) for candidate in candidates),
            "unresolved": sum(len(candidate.unresolved_dependencies) for candidate in candidates),
            "vendor_primitives": sum(1 for issue in dependency_issues if issue.category == "vendor_primitive"),
            "external_libraries": sum(1 for issue in dependency_issues if issue.category == "external_library"),
            "duplicate_modules": hierarchy.duplicate_modules,
            "issues": [asdict(issue) for issue in dependency_issues],
        },
        "verification": verification_counts,
        "quality_tiers": quality_tiers,
        "quality_gate_counts": quality_gate_counts,
        "skills": skills,
    }
    (output_root / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
