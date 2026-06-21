from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import QueryPlan
from .retriever import retrieve_skills


def retrieve_rtl_skills_impl(
    intent: str,
    positive_terms: list[str],
    negative_terms: list[str],
    likely_categories: list[str],
    likely_interfaces: list[str],
    required_features: list[str],
    skills_root: str = "skills",
    limit: int = 10,
) -> dict[str, Any]:
    plan = QueryPlan.from_dict(
        {
            "intent": intent,
            "positive_terms": positive_terms,
            "negative_terms": negative_terms,
            "likely_categories": likely_categories,
            "likely_interfaces": likely_interfaces,
            "required_features": required_features,
        }
    )
    results = retrieve_skills(plan, Path(skills_root), limit=limit)
    return {
        "query_plan": plan.to_dict(),
        "results": [result.to_dict() for result in results],
    }


try:
    from langchain_core.tools import tool
except Exception:  # pragma: no cover - exercised when LangChain is absent
    tool = None


if tool is not None:

    @tool
    def retrieve_rtl_skills(
        intent: str,
        positive_terms: list[str],
        negative_terms: list[str],
        likely_categories: list[str],
        likely_interfaces: list[str],
        required_features: list[str],
        skills_root: str = "skills",
        limit: int = 10,
    ) -> dict[str, Any]:
        """Retrieve ranked RTL skills from a query_plan.json-shaped input."""
        return retrieve_rtl_skills_impl(
            intent=intent,
            positive_terms=positive_terms,
            negative_terms=negative_terms,
            likely_categories=likely_categories,
            likely_interfaces=likely_interfaces,
            required_features=required_features,
            skills_root=skills_root,
            limit=limit,
        )

else:

    def retrieve_rtl_skills(
        intent: str,
        positive_terms: list[str],
        negative_terms: list[str],
        likely_categories: list[str],
        likely_interfaces: list[str],
        required_features: list[str],
        skills_root: str = "skills",
        limit: int = 10,
    ) -> dict[str, Any]:
        return retrieve_rtl_skills_impl(
            intent=intent,
            positive_terms=positive_terms,
            negative_terms=negative_terms,
            likely_categories=likely_categories,
            likely_interfaces=likely_interfaces,
            required_features=required_features,
            skills_root=skills_root,
            limit=limit,
        )

