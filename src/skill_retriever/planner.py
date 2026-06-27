from __future__ import annotations

from .models import QueryPlan


def build_query_plan(user_query: str, llm) -> QueryPlan:
    try:
        from pydantic import BaseModel, Field
    except ModuleNotFoundError as exc:
        raise RuntimeError("missing Python dependency: pydantic is required for LLM query planning") from exc

    class QueryPlanOutput(BaseModel):
        intent: str = Field(min_length=1)
        positive_terms: list[str]
        negative_terms: list[str]
        likely_categories: list[str]
        likely_interfaces: list[str]
        required_features: list[str]

    payload = llm.complete_structured(
        [
            {
                "role": "system",
                "content": (
                    "You convert a user's RTL design request into query_plan.json for deterministic retrieval. "
                    "Return only a JSON object with exactly these fields: intent, positive_terms, "
                    "negative_terms, likely_categories, likely_interfaces, required_features. "
                    "Use short Verilog/RTL retrieval terms from the user request and likely hardware concepts. "
                    "negative_terms must contain only concepts the user explicitly rejects or excludes; "
                    "never put a likely target protocol, likely implementation, or inferred skill family in negative_terms. "
                    "If a request describes an idle-high single-wire byte frame with start/data/stop markers, "
                    "include UART/uart transmitter terms unless the user explicitly says not UART. "
                    "Do not select a final skill."
                ),
            },
            {"role": "user", "content": user_query},
        ],
        QueryPlanOutput,
        temperature=0.0,
    )
    return QueryPlan.from_dict(payload.model_dump())
