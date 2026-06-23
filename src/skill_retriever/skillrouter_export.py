from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .benchmark import load_benchmark
from .models import QueryPlan
from .retriever import flatten


def iter_skill_dirs(skills_root: Path) -> Iterable[Path]:
    if not skills_root.exists():
        return []
    return sorted(path.parent for path in skills_root.rglob("module_info.json"))


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def export_skillrouter_records(skills_root: Path) -> list[dict[str, Any]]:
    records = []
    for skill_dir in iter_skill_dirs(skills_root):
        module_info_path = skill_dir / "module_info.json"
        try:
            module_info = load_json(module_info_path)
        except Exception:
            continue
        skill_spec = {}
        skill_spec_path = skill_dir / "skill_spec.json"
        if skill_spec_path.exists():
            try:
                skill_spec = load_json(skill_spec_path)
            except Exception:
                skill_spec = {}
        readme_path = skill_dir / "README.md"
        readme = readme_path.read_text(encoding="utf-8", errors="ignore") if readme_path.exists() else ""
        skill_id = str(skill_spec.get("skill_id") or module_info.get("name") or skill_dir.name)
        records.append(
            {
                "skill_id": skill_id,
                "name": str(module_info.get("name") or skill_id),
                "description": description_text(module_info, skill_spec),
                "body": body_text(module_info, skill_spec, readme),
                "source_path": skill_dir.as_posix(),
            }
        )
    return records


def description_text(module_info: dict[str, Any], skill_spec: dict[str, Any]) -> str:
    claim_texts = [
        str(claim.get("claim"))
        for claim in skill_spec.get("claims", [])
        if isinstance(claim, dict) and claim.get("kind") in {"function", "interface", "behavior"}
    ]
    if claim_texts:
        return " ".join(claim_texts[:2])
    return str(module_info.get("description") or module_info.get("functional_summary") or module_info.get("name") or "")


def body_text(module_info: dict[str, Any], skill_spec: dict[str, Any], readme: str) -> str:
    sections = []
    retrieval_text = str(skill_spec.get("retrieval_text") or "").strip()
    if retrieval_text:
        sections.append(f"Skill Spec Retrieval Text:\n{retrieval_text}")
    claims = [
        f"- {claim.get('kind', 'claim')} [{claim.get('status', 'unknown')}]: {claim.get('claim', '')}"
        for claim in skill_spec.get("claims", [])
        if isinstance(claim, dict)
    ]
    if claims:
        sections.append("Evidence-linked Claims:\n" + "\n".join(claims))
    unknowns = [str(item) for item in flatten(skill_spec.get("unknowns")) if str(item).strip()]
    if unknowns:
        sections.append("Unknowns and Risks:\n" + "\n".join(f"- {item}" for item in unknowns))
    sections.append("Module Info:\n" + json.dumps(module_info, ensure_ascii=False, sort_keys=True))
    if readme:
        sections.append("README:\n" + readme)
    return "\n\n".join(sections)


def write_jsonl(records: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def query_text_from_plan(plan: QueryPlan) -> str:
    parts = [
        plan.intent,
        "positive terms: " + ", ".join(plan.positive_terms),
        "likely categories: " + ", ".join(plan.likely_categories),
        "likely interfaces: " + ", ".join(plan.likely_interfaces),
        "required features: " + ", ".join(plan.required_features),
    ]
    if plan.negative_terms:
        parts.append("avoid: " + ", ".join(plan.negative_terms))
    return "\n".join(part for part in parts if part.strip())


def prepare_skillrouter_query_data(
    plan: QueryPlan,
    skills_root: Path,
    output_dir: Path,
    tiers: list[str] | None = None,
    task_id: str = "local_query",
) -> dict[str, Any]:
    tiers = tiers or ["easy"]
    invalid_tiers = sorted(set(tiers) - {"easy", "hard"})
    if invalid_tiers:
        raise ValueError(f"unsupported SkillRouter tier(s): {', '.join(invalid_tiers)}")
    records = export_skillrouter_records(skills_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    task = {
        "task_id": task_id,
        "domain": "rtl",
        "instruction_text": query_text_from_plan(plan),
        "difficulty": "local",
        "num_skills": 0,
        "skill_names": [],
        "tags": ["rtl", "local-skillrouter-query"],
        "excluded": False,
    }
    write_jsonl([task], output_dir / "tasks.jsonl")
    (output_dir / "relevance.json").write_text(
        json.dumps({task_id: {"task_type": "local_query", "gt_skill_ids": [], "relevance": {}}}, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "dataset_name": "mini-rtl-agent-local-skillrouter-query",
        "task_id": task_id,
        "skills_root": str(skills_root),
        "records": len(records),
        "tiers": tiers,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    for tier in tiers:
        write_jsonl(records, output_dir / tier / "part-00000.jsonl")
    return {"task": task, "records": len(records), "tiers": tiers, "data_root": str(output_dir)}


def prepare_skillrouter_benchmark_data(
    benchmark_path: Path,
    skills_root: Path,
    output_dir: Path,
    tiers: list[str] | None = None,
) -> dict[str, Any]:
    tiers = tiers or ["easy"]
    invalid_tiers = sorted(set(tiers) - {"easy", "hard"})
    if invalid_tiers:
        raise ValueError(f"unsupported SkillRouter tier(s): {', '.join(invalid_tiers)}")
    cases = load_benchmark(benchmark_path)
    records = export_skillrouter_records(skills_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    relevance = {}
    for case in cases:
        tasks.append(
            {
                "task_id": case.case_id,
                "domain": "rtl",
                "instruction_text": query_text_from_plan(case.query_plan),
                "difficulty": "local",
                "num_skills": len(case.relevant_skill_ids),
                "skill_names": case.relevant_skill_ids,
                "tags": ["rtl", "local-skillrouter-benchmark"],
                "excluded": False,
            }
        )
        relevance[case.case_id] = {
            "task_type": "local_benchmark",
            "gt_skill_ids": case.relevant_skill_ids,
            "relevance": {skill_id: 1 for skill_id in case.relevant_skill_ids},
        }
    write_jsonl(tasks, output_dir / "tasks.jsonl")
    (output_dir / "relevance.json").write_text(json.dumps(relevance, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "dataset_name": "mini-rtl-agent-local-skillrouter-benchmark",
        "benchmark": str(benchmark_path),
        "skills_root": str(skills_root),
        "records": len(records),
        "tasks": len(tasks),
        "tiers": tiers,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    for tier in tiers:
        write_jsonl(records, output_dir / tier / "part-00000.jsonl")
    return {"tasks": len(tasks), "records": len(records), "tiers": tiers, "data_root": str(output_dir)}
