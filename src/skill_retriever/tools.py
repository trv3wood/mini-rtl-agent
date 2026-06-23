from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import QueryPlan
from .retriever import retrieve_skills
from .router_response import build_router_response
from .skillrouter_import import fuse_rankings, import_skillrouter_results


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


def route_rtl_skill_impl(
    intent: str,
    positive_terms: list[str],
    negative_terms: list[str],
    likely_categories: list[str],
    likely_interfaces: list[str],
    required_features: list[str],
    skills_root: str = "skills",
    limit: int = 5,
    external_json: str | None = None,
    task_id: str = "local_query",
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
    lexical = retrieve_skills(plan, Path(skills_root), limit=limit)
    if external_json:
        semantic = import_skillrouter_results(Path(external_json), task_id, Path(skills_root), plan, limit=limit)
        ranked = fuse_rankings(lexical, semantic, limit=limit)
    else:
        ranked = lexical
    return build_router_response(plan, ranked, limit=limit)


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

    @tool
    def route_rtl_skill(
        intent: str,
        positive_terms: list[str],
        negative_terms: list[str],
        likely_categories: list[str],
        likely_interfaces: list[str],
        required_features: list[str],
        skills_root: str = "skills",
        limit: int = 5,
        external_json: str | None = None,
        task_id: str = "local_query",
    ) -> dict[str, Any]:
        """Return a downstream-agent RTL skill routing contract from query_plan.json-shaped input."""
        return route_rtl_skill_impl(
            intent=intent,
            positive_terms=positive_terms,
            negative_terms=negative_terms,
            likely_categories=likely_categories,
            likely_interfaces=likely_interfaces,
            required_features=required_features,
            skills_root=skills_root,
            limit=limit,
            external_json=external_json,
            task_id=task_id,
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

    def route_rtl_skill(
        intent: str,
        positive_terms: list[str],
        negative_terms: list[str],
        likely_categories: list[str],
        likely_interfaces: list[str],
        required_features: list[str],
        skills_root: str = "skills",
        limit: int = 5,
        external_json: str | None = None,
        task_id: str = "local_query",
    ) -> dict[str, Any]:
        return route_rtl_skill_impl(
            intent=intent,
            positive_terms=positive_terms,
            negative_terms=negative_terms,
            likely_categories=likely_categories,
            likely_interfaces=likely_interfaces,
            required_features=required_features,
            skills_root=skills_root,
            limit=limit,
            external_json=external_json,
            task_id=task_id,
        )
