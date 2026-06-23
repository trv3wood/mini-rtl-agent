from __future__ import annotations

from pathlib import Path
from typing import Any

from .benchmark import aggregate, evaluate_ranked_ids, load_benchmark
from .models import QueryPlan, RankedSkill
from .retriever import retrieve_skills
from .skillrouter_import import fused_payload, fuse_rankings, import_skillrouter_results, load_skillrouter_ids


def name_list(results: list[RankedSkill]) -> list[str]:
    return [item.name for item in results]


def overlap_at_k(left: list[RankedSkill], right: list[RankedSkill], k: int) -> list[str]:
    left_names = name_list(left[:k])
    right_names = set(name_list(right[:k]))
    return [name for name in left_names if name in right_names]


def compare_with_external_skillrouter(
    plan: QueryPlan,
    *,
    skills_root: Path,
    external_json: Path,
    task_id: str = "local_query",
    limit: int = 10,
) -> dict[str, Any]:
    lexical = retrieve_skills(plan, skills_root, limit=limit)
    raw_external = load_skillrouter_ids(external_json, task_id)[:limit]
    semantic = import_skillrouter_results(external_json, task_id, skills_root, plan, limit=limit)
    fused = fuse_rankings(lexical, semantic, limit=limit)
    payload = fused_payload(plan, lexical, semantic, fused)
    payload["comparison"] = {
        "task_id": task_id,
        "external_json": str(external_json),
        "limit": limit,
        "local_top1": lexical[0].name if lexical else None,
        "external_top1": raw_external[0] if raw_external else None,
        "semantic_scored_top1": semantic[0].name if semantic else None,
        "fused_top1": fused[0].name if fused else None,
        "local_top_k": name_list(lexical),
        "external_top_k": raw_external,
        "semantic_scored_top_k": name_list(semantic),
        "fused_top_k": name_list(fused),
        "local_external_overlap": [name for name in name_list(lexical) if name in set(raw_external)],
        "local_fused_overlap": overlap_at_k(lexical, fused, limit),
    }
    return payload


def compare_benchmark_with_external_skillrouter(
    dataset_path: Path,
    *,
    skills_root: Path,
    external_json: Path,
    limit: int = 10,
) -> dict[str, Any]:
    cases = load_benchmark(dataset_path)
    local_cases = []
    external_cases = []
    semantic_cases = []
    fused_cases = []
    combined_cases = []

    for case in cases:
        lexical = retrieve_skills(case.query_plan, skills_root, limit=limit)
        raw_external = load_skillrouter_ids(external_json, case.case_id)[:limit]
        semantic = import_skillrouter_results(external_json, case.case_id, skills_root, case.query_plan, limit=limit)
        fused = fuse_rankings(lexical, semantic, limit=limit)

        local_eval = evaluate_ranked_ids(case, name_list(lexical))
        external_eval = evaluate_ranked_ids(case, raw_external)
        semantic_eval = evaluate_ranked_ids(case, name_list(semantic))
        fused_eval = evaluate_ranked_ids(case, name_list(fused))
        local_cases.append(local_eval)
        external_cases.append(external_eval)
        semantic_cases.append(semantic_eval)
        fused_cases.append(fused_eval)
        combined_cases.append(
            {
                "id": case.case_id,
                "relevant_skill_ids": case.relevant_skill_ids,
                "local_ranked_skill_ids": local_eval["ranked_skill_ids"],
                "external_ranked_skill_ids": external_eval["ranked_skill_ids"],
                "semantic_scored_ranked_skill_ids": semantic_eval["ranked_skill_ids"],
                "fused_ranked_skill_ids": fused_eval["ranked_skill_ids"],
                "local_first_relevant_rank": local_eval["first_relevant_rank"],
                "external_first_relevant_rank": external_eval["first_relevant_rank"],
                "semantic_scored_first_relevant_rank": semantic_eval["first_relevant_rank"],
                "fused_first_relevant_rank": fused_eval["first_relevant_rank"],
            }
        )

    return {
        "dataset": str(dataset_path),
        "skills_root": str(skills_root),
        "external_json": str(external_json),
        "limit": limit,
        "case_count": len(cases),
        "metrics": {
            "local": aggregate(local_cases),
            "external": aggregate(external_cases),
            "semantic_scored": aggregate(semantic_cases),
            "fused": aggregate(fused_cases),
        },
        "cases": combined_cases,
    }
