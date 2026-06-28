from __future__ import annotations

from pathlib import Path
from typing import Any

from .planner import build_query_plan
from .backends.rg_rerank.retriever import retrieve_skills


def retrieve_for_user_query(
    user_query: str,
    llm,
    *,
    skills_root: Path = Path("skills"),
    limit: int = 10,
) -> dict[str, Any]:
    plan = build_query_plan(user_query, llm)
    results = retrieve_skills(plan, skills_root, limit=limit)
    return {
        "user_query": user_query,
        "query_plan": plan.to_dict(),
        "results": [result.to_dict() for result in results],
    }
