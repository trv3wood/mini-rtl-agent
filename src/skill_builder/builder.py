from __future__ import annotations

import json
from dataclasses import asdict, replace
import shutil
from pathlib import Path

from src.utils.llm import ChatClient, OpenAICompatibleLLM

from .classifier import classify
from .frontend import get_last_parse_warnings, parse_project
from .generator import (
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
from .models import ModuleInfo, SkillCandidate, VerificationResult
from .scanner import scan_rtl_files
from .schema import validate_module_info
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
    }


def quality_json(
    candidate: SkillCandidate,
    module: ModuleInfo,
    schema_ok: bool,
    verification: VerificationResult,
    tier: str,
) -> dict:
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
        },
        "schema_ok": schema_ok,
        "quality_tier": tier,
    }


def write_skill(module: ModuleInfo, candidate: SkillCandidate, output_root: Path, repo_path: Path) -> dict:
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
    atomic_write_text(examples_dir / "instantiation.v", generate_instantiation(module))
    tb_path = examples_dir / f"tb_{module.name}.v"
    atomic_write_text(tb_path, generate_testbench(module))
    packaged_source_files = copy_candidate_sources(candidate, skill_dir, repo_path)
    verification_candidate = replace(candidate, source_files=packaged_source_files)
    verification = verify_candidate(verification_candidate, skill_dir, tb_path)
    tier = quality_tier(candidate, not schema_errors, verification)
    atomic_write_json(skill_dir / "manifest.json", manifest_json(candidate, repo_path))
    atomic_write_json(skill_dir / "quality.json", quality_json(candidate, module, not schema_errors, verification, tier))

    files_ok = all(
        path.exists()
        for path in (
            skill_dir / "module_info.json",
            skill_dir / "README.md",
            skill_dir / "template.v",
            skill_dir / "manifest.json",
            skill_dir / "quality.json",
            examples_dir / "instantiation.v",
            examples_dir / f"tb_{module.name}.v",
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
            "quality": str(skill_dir / "quality.json"),
            "instantiation": str(examples_dir / "instantiation.v"),
            "testbench": str(examples_dir / f"tb_{module.name}.v"),
        },
    }


def clean_output_root(output_root: Path) -> None:
    if not output_root.exists():
        return
    for child in output_root.iterdir():
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
    module_candidate_pairs: list[tuple[ModuleInfo, SkillCandidate]] = []
    parse_warnings = get_last_parse_warnings()
    for module_ir in module_irs:
        parse_warnings.extend(module_ir.parse_warnings)
    active_llm = llm
    if candidates and active_llm is None:
        active_llm = OpenAICompatibleLLM()
    module_lookup = {(module_ir.name, module_ir.source_file): module_ir for module_ir in module_irs}
    for candidate in candidates:
        module_ir = module_lookup.get((candidate.root_module, candidate.root_source))
        if module_ir is None:
            module_ir = hierarchy.modules.get(candidate.root_module)
        if module_ir is None:
            continue
        module = classify(module_ir.to_module_info(), active_llm)
        modules.append(module)
        module_candidate_pairs.append((module, candidate))

    skills = [write_skill(module, candidate, output_root, repo_path) for module, candidate in module_candidate_pairs]
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
    dependency_issues = [issue for issues in hierarchy.dependency_issues.values() for issue in issues]
    report = {
        "input_repo": str(repo_path),
        "output_root": str(output_root),
        "candidate_mode": candidate_mode,
        "rtl_files_scanned": len(rtl_files),
        "modules_extracted": len(module_irs),
        "skills_generated": len(skills),
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
        "skills": skills,
    }
    (output_root / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
