from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import QueryPlan, RankedSkill
from .retriever import retrieve_skills


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    query_plan: QueryPlan
    relevant_skill_ids: list[str]


def load_benchmark(path: Path) -> list[BenchmarkCase]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"benchmark file not found or unreadable: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid benchmark JSON: {exc}") from exc
    items = data.get("cases") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("benchmark must be a list or an object with a cases list")
    cases = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"benchmark case {idx} must be an object")
        case_id = str(item.get("id") or item.get("case_id") or f"case_{idx + 1}")
        relevant = item.get("relevant_skill_ids")
        if not isinstance(relevant, list) or not relevant:
            raise ValueError(f"benchmark case {case_id} must include non-empty relevant_skill_ids")
        plan_data = item.get("query_plan")
        if not isinstance(plan_data, dict):
            raise ValueError(f"benchmark case {case_id} must include query_plan object")
        cases.append(
            BenchmarkCase(
                case_id=case_id,
                query_plan=QueryPlan.from_dict(plan_data),
                relevant_skill_ids=[str(skill_id) for skill_id in relevant],
            )
        )
    return cases


def evaluate_case(case: BenchmarkCase, results: list[RankedSkill]) -> dict[str, Any]:
    ranked_names = [result.name for result in results]
    relevant = set(case.relevant_skill_ids)
    first_rank = next((idx + 1 for idx, name in enumerate(ranked_names) if name in relevant), None)
    return {
        "id": case.case_id,
        "relevant_skill_ids": case.relevant_skill_ids,
        "ranked_skill_ids": ranked_names,
        "hit_at_1": 1.0 if ranked_names[:1] and ranked_names[0] in relevant else 0.0,
        "mrr_at_10": 0.0 if first_rank is None or first_rank > 10 else 1.0 / first_rank,
        "recall_at_5": recall_at_k(ranked_names, relevant, 5),
        "recall_at_10": recall_at_k(ranked_names, relevant, 10),
        "recall_at_20": recall_at_k(ranked_names, relevant, 20),
        "first_relevant_rank": first_rank,
    }


def run_benchmark(dataset_path: Path, skills_root: Path, limit: int = 20) -> dict[str, Any]:
    cases = load_benchmark(dataset_path)
    case_results = []
    for case in cases:
        ranked = retrieve_skills(case.query_plan, skills_root, limit=limit)
        case_results.append(evaluate_case(case, ranked))
    return {
        "dataset": str(dataset_path),
        "skills_root": str(skills_root),
        "limit": limit,
        "case_count": len(case_results),
        "metrics": aggregate(case_results),
        "cases": case_results,
    }


def aggregate(case_results: list[dict[str, Any]]) -> dict[str, float]:
    if not case_results:
        return {
            "hit_at_1": 0.0,
            "mrr_at_10": 0.0,
            "recall_at_5": 0.0,
            "recall_at_10": 0.0,
            "recall_at_20": 0.0,
        }
    keys = ("hit_at_1", "mrr_at_10", "recall_at_5", "recall_at_10", "recall_at_20")
    return {key: sum(float(item[key]) for item in case_results) / len(case_results) for key in keys}


def recall_at_k(ranked_names: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(ranked_names[:k]) & relevant) / len(relevant)
