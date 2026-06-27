from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .benchmark import aggregate, evaluate_ranked_ids
from .models import QueryPlan
from .workflow import retrieve_for_user_query


@dataclass(frozen=True)
class UserQueryCase:
    case_id: str
    user_query: str
    relevant_skill_ids: list[str]
    notes: str = ""


def load_user_query_benchmark(path: Path) -> list[UserQueryCase]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"user-query benchmark file not found or unreadable: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid user-query benchmark JSON: {exc}") from exc
    items = data.get("cases") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("user-query benchmark must be a list or an object with a cases list")
    cases = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"user-query benchmark case {idx} must be an object")
        case_id = str(item.get("id") or item.get("case_id") or f"case_{idx + 1}")
        user_query = item.get("user_query")
        if not isinstance(user_query, str) or not user_query.strip():
            raise ValueError(f"user-query benchmark case {case_id} must include user_query")
        relevant = item.get("relevant_skill_ids")
        if not isinstance(relevant, list) or not relevant:
            raise ValueError(f"user-query benchmark case {case_id} must include non-empty relevant_skill_ids")
        cases.append(
            UserQueryCase(
                case_id=case_id,
                user_query=user_query,
                relevant_skill_ids=[str(skill_id) for skill_id in relevant],
                notes=str(item.get("notes") or ""),
            )
        )
    return cases


def run_user_query_benchmark(
    dataset_path: Path,
    skills_root: Path,
    llm,
    *,
    limit: int = 10,
    max_cases: int | None = None,
) -> dict[str, Any]:
    cases = load_user_query_benchmark(dataset_path)
    if max_cases is not None:
        cases = cases[:max_cases]
    results = []
    for case in cases:
        payload = retrieve_for_user_query(case.user_query, llm, skills_root=skills_root, limit=limit)
        ranked_names = [item["name"] for item in payload["results"]]
        eval_payload = evaluate_ranked_ids(
            _query_plan_case(case.case_id, case.relevant_skill_ids),
            ranked_names,
        )
        results.append(
            {
                **eval_payload,
                "user_query": case.user_query,
                "notes": case.notes,
                "query_plan": payload["query_plan"],
                "results": payload["results"],
            }
        )
    return {
        "dataset": str(dataset_path),
        "skills_root": str(skills_root),
        "limit": limit,
        "case_count": len(results),
        "metrics": aggregate(results),
        "cases": results,
    }


def _query_plan_case(case_id: str, relevant_skill_ids: list[str]):
    from .benchmark import BenchmarkCase

    return BenchmarkCase(
        case_id=case_id,
        query_plan=QueryPlan(
            intent="",
            positive_terms=[],
            negative_terms=[],
            likely_categories=[],
            likely_interfaces=[],
            required_features=[],
        ),
        relevant_skill_ids=relevant_skill_ids,
    )
