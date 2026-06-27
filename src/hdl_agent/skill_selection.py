from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.skill_retriever.models import QueryPlan
from src.utils.llm import ChatClient


Confidence = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class SkillSelectionDecision:
    selected_skill: str
    selected_rank: int
    confidence: Confidence
    reason: str
    rejected: list[dict[str, str]]


class SkillSelectionOutput(BaseModel):
    selected_skill: str = Field(min_length=1)
    selected_rank: int = Field(ge=1)
    confidence: Confidence
    reason: str = Field(min_length=1)
    rejected: list[dict[str, str]] = Field(default_factory=list)


def select_skill_from_candidates(
    *,
    user_request: str,
    query_plan: QueryPlan,
    candidates: list[dict[str, Any]],
    llm: ChatClient,
) -> SkillSelectionDecision:
    if not candidates:
        raise RuntimeError("cannot select a skill from an empty candidate list")
    payload = llm.complete_structured(
        build_skill_selection_prompt(
            user_request=user_request,
            query_plan=query_plan,
            candidates=candidates,
        ),
        SkillSelectionOutput,
        temperature=0.0,
    )
    candidate_names = [str(item["name"]) for item in candidates]
    if payload.selected_skill not in candidate_names:
        raise RuntimeError(
            f"LLM selected skill outside retriever top-k: {payload.selected_skill}; "
            f"allowed={candidate_names}"
        )
    actual_rank = candidate_names.index(payload.selected_skill) + 1
    if payload.selected_rank != actual_rank:
        payload = payload.model_copy(update={"selected_rank": actual_rank})
    if payload.confidence == "low":
        raise RuntimeError(f"LLM skill selection confidence is low: {payload.reason}")
    return SkillSelectionDecision(
        selected_skill=payload.selected_skill,
        selected_rank=payload.selected_rank,
        confidence=payload.confidence,
        reason=payload.reason,
        rejected=payload.rejected,
    )


def build_skill_selection_prompt(
    *,
    user_request: str,
    query_plan: QueryPlan,
    candidates: list[dict[str, Any]],
) -> list[dict[str, str]]:
    candidate_summaries = []
    for index, item in enumerate(candidates, start=1):
        card = item.get("compact_card", {})
        candidate_summaries.append(
            {
                "rank": index,
                "name": item.get("name"),
                "score": item.get("score"),
                "path": item.get("path"),
                "why_matched": item.get("why_matched", []),
                "core_function": card.get("core_function", ""),
                "algorithm": card.get("algorithm", ""),
                "interface_signature": card.get("interface_signature", ""),
                "keywords": card.get("keywords", []),
                "structure": card.get("structure", []),
                "retrieval_text": card.get("retrieval_text", ""),
            }
        )
    return [
        {
            "role": "system",
            "content": (
                "You select one RTL skill from a deterministic retriever top-k candidate list. "
                "Choose only from the provided candidates; never invent a skill outside the list. "
                "Use the human request, query_plan, compact-card summaries, and why_matched evidence. "
                "Prefer the skill whose behavior and interface best match the requested IP, not necessarily rank 1. "
                "If no candidate is suitable, choose the least bad candidate with confidence='low' and explain why. "
                "Return structured JSON only with: selected_skill, selected_rank, confidence, reason, rejected."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Human HDL request:\n{user_request}\n\n"
                f"query_plan:\n{query_plan.to_dict()}\n\n"
                f"top_k_candidates:\n{candidate_summaries}"
            ),
        },
    ]
