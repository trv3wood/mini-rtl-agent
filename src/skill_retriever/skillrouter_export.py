from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .benchmark import load_benchmark
from .models import QueryPlan


def iter_skill_dirs(skills_root: Path) -> Iterable[Path]:
    if not skills_root.exists():
        return []
    return sorted(path.parent for path in skills_root.rglob("compact_card.json"))


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def export_skillrouter_records(skills_root: Path) -> list[dict[str, Any]]:
    records = []
    for skill_dir in iter_skill_dirs(skills_root):
        compact_card_path = skill_dir / "compact_card.json"
        if compact_card_path.exists():
            try:
                records.append(record_from_compact_card(skill_dir, load_json(compact_card_path)))
            except Exception:
                continue
    return records


def record_from_compact_card(skill_dir: Path, card: dict[str, Any]) -> dict[str, Any]:
    skill_path = skill_dir / "skill.json"
    skill = load_json(skill_path) if skill_path.exists() else {}
    skill_id = str(card.get("skill_id") or skill.get("skill_id") or card.get("name") or skill_dir.name)
    body = {
        "core_function": card.get("core_function", ""),
        "algorithm": card.get("algorithm", ""),
        "structure": card.get("structure", []),
        "interface_signature": card.get("interface_signature", ""),
        "keywords": card.get("keywords", []),
        "retrieval_text": card.get("retrieval_text", ""),
        "rtl_files": skill.get("rtl_files", []),
    }
    return {
        "skill_id": skill_id,
        "name": str(card.get("name") or skill_id),
        "description": str(card.get("core_function") or card.get("retrieval_text") or skill_id),
        "body": json.dumps(body, ensure_ascii=False, sort_keys=True),
        "source_path": skill_dir.as_posix(),
    }


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
