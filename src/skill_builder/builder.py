from __future__ import annotations

import json
from dataclasses import asdict
import shutil
from pathlib import Path

from .frontend import get_last_parse_warnings, parse_project
from .hierarchy import build_module_hierarchy
from .hierarchy import build_skill_candidates
from .hierarchy import module_dependency_graph
from .llm_client import AnnotationResult, SkillAnnotator, create_annotator
from .minimal import (
    build_compact_card,
    build_minimal_skill_json,
    copy_minimal_rtl,
    validate_compact_card,
    validate_minimal_skill,
)
from .models import ModuleIR, ModuleInfo, SkillCandidate
from .scanner import scan_rtl_files
from .semantic import annotate_module


class SkillBuilderError(RuntimeError):
    pass


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def atomic_write_json(path: Path, data: dict) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def write_minimal_skill(
    module: ModuleInfo,
    candidate: SkillCandidate,
    output_root: Path,
    repo_path: Path,
    semantic_skill: dict | None = None,
) -> dict:
    skill_name = candidate.skill_id
    skill_dir = output_root / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    rtl_files = copy_minimal_rtl(candidate, skill_dir, repo_path)
    skill_json = build_minimal_skill_json(module, candidate, repo_path, rtl_files, semantic_skill)
    card_json = build_compact_card(skill_json)
    schema_errors = validate_minimal_skill(skill_json) + validate_compact_card(card_json)
    if schema_errors:
        raise SkillBuilderError(f"generated minimal skill invalid for {module.name}: {schema_errors}")
    atomic_write_json(skill_dir / "skill.json", skill_json)
    atomic_write_json(skill_dir / "compact_card.json", card_json)
    return {
        "name": module.name,
        "skill_name": skill_name,
        "source_path": str(module.source_path),
        "category": module.category,
        "patterns": module.patterns,
        "interfaces": module.interfaces,
        "candidate_kind": candidate.candidate_kind,
        "granularity": skill_json["granularity"],
        "is_self_contained": candidate.is_self_contained,
        "dependency_modules": candidate.dependency_modules,
        "unresolved_dependencies": candidate.unresolved_dependencies,
        "vendor_primitives": candidate.vendor_primitives,
        "schema_ok": True,
        "schema_errors": [],
        "paths": {
            "skill": str(skill_dir / "skill.json"),
            "compact_card": str(skill_dir / "compact_card.json"),
            "rtl": str(skill_dir / "rtl"),
        },
        "retrieval_text_words": len(card_json["retrieval_text"].split()),
        "keyword_count": len(card_json["keywords"]),
        "semantic_backend": semantic_skill.get("_semantic_backend", "fallback") if semantic_skill else "fallback",
    }


def clean_output_root(output_root: Path) -> None:
    if not output_root.exists():
        return
    for child in output_root.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def build_skill_library(
    repo_path: Path,
    output_root: Path | None = None,
    clean: bool = False,
    candidate_mode: str = "all",
    annotator: SkillAnnotator | None = None,
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

    if annotator is None:
        annotator = create_annotator()

    rtl_files = scan_rtl_files(repo_path)
    module_irs = parse_project(rtl_files)
    hierarchy = build_module_hierarchy(module_irs)
    dependency_graph = module_dependency_graph(hierarchy)
    candidates = build_skill_candidates(hierarchy, include_internal=candidate_mode == "all")
    modules: list[ModuleInfo] = []
    module_candidate_pairs: list[tuple[ModuleInfo, ModuleIR, SkillCandidate]] = []
    parse_warnings = get_last_parse_warnings()
    for module_ir in module_irs:
        parse_warnings.extend(module_ir.parse_warnings)
    module_lookup = {(module_ir.name, module_ir.source_file): module_ir for module_ir in module_irs}
    for candidate in candidates:
        module_ir = module_lookup.get((candidate.root_module, candidate.root_source))
        if module_ir is None:
            module_ir = hierarchy.modules.get(candidate.root_module)
        if module_ir is None:
            continue
        module = module_ir.to_module_info()
        modules.append(module)
        module_candidate_pairs.append((module, module_ir, candidate))

    project_name = repo_path.name

    semantic_contexts: list[dict] = []
    annotation_results: list[AnnotationResult] = []
    semantic_backend = "fallback"
    llm_used = False
    fallback_count = 0
    taxonomy_unmapped_terms = 0
    total_taxonomy_warnings: list[str] = []

    skills: list[dict] = []
    for module, module_ir, candidate in module_candidate_pairs:
        try:
            ctx = annotate_module(module_ir, candidate, hierarchy, project_name, annotator)
        except Exception as exc:
            ctx = annotate_module(module_ir, candidate, hierarchy, project_name, annotator=None)
            if not isinstance(ctx.result, AnnotationResult):
                pass
            ctx.result.warnings.append(f"annotation recovery after exception: {exc}")

        annotation_results.append(ctx.result)
        if ctx.result.backend != "fallback":
            semantic_backend = ctx.result.backend
        if ctx.result.llm_used:
            llm_used = True
        if ctx.result.backend == "fallback":
            fallback_count += 1
        taxonomy_unmapped_terms += len(ctx.taxonomy.unmapped_terms)
        total_taxonomy_warnings.extend(ctx.taxonomy.warnings)

        semantic_contexts.append({
            "module": module.name,
            "backend": ctx.result.backend,
            "llm_used": ctx.result.llm_used,
            "warnings": ctx.result.warnings,
            "taxonomy_unmapped": ctx.taxonomy.unmapped_terms,
            "taxonomy_warnings": ctx.taxonomy.warnings,
        })

        skill = write_minimal_skill(module, candidate, output_root, repo_path, ctx.merged)
        skills.append(skill)

    if fallback_count == len(module_candidate_pairs):
        semantic_backend = "fallback"
        llm_used = False

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
        "source_compile_passed": sum(1 for skill in skills if skill.get("verification", {}).get("source_compile") == "passed"),
        "source_compile_failed": sum(
            1 for skill in skills if skill.get("verification", {}).get("source_compile", "skipped") not in {"passed", "skipped"}
        ),
        "tb_compile_passed": sum(1 for skill in skills if skill.get("verification", {}).get("generated_tb_compile") == "passed"),
        "tb_compile_failed": sum(
            1 for skill in skills if skill.get("verification", {}).get("generated_tb_compile", "skipped") not in {"passed", "skipped"}
        ),
        "simulation_passed": sum(1 for skill in skills if skill.get("verification", {}).get("simulation") == "passed"),
        "simulation_failed": sum(
            1 for skill in skills if skill.get("verification", {}).get("simulation", "skipped") not in {"passed", "skipped"}
        ),
        "simulation_skipped": sum(1 for skill in skills if skill.get("verification", {}).get("simulation", "skipped") == "skipped"),
    }
    quality_tiers = {tier: 0 for tier in ("rejected", "bronze", "silver", "gold_candidate")}
    for skill in skills:
        if "quality_tier" in skill:
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
        "package_format": "minimal",
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
            "mermaid_direct": None,
            "mermaid_closure": None,
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
        "semantic": {
            "backend": semantic_backend,
            "llm_used": llm_used,
            "fallback_count": fallback_count,
            "total_modules": len(module_candidate_pairs),
            "taxonomy_unmapped_terms": taxonomy_unmapped_terms,
            "taxonomy_warnings": total_taxonomy_warnings[:20],
            "per_module": semantic_contexts,
        },
        "skills": skills,
    }
    (output_root / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
