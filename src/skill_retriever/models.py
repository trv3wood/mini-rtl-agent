from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REQUIRED_QUERY_PLAN_FIELDS = {
    "intent",
    "positive_terms",
    "negative_terms",
    "likely_categories",
    "likely_interfaces",
    "required_features",
}


@dataclass(frozen=True)
class QueryPlan:
    intent: str
    positive_terms: list[str]
    negative_terms: list[str]
    likely_categories: list[str]
    likely_interfaces: list[str]
    required_features: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QueryPlan":
        missing = REQUIRED_QUERY_PLAN_FIELDS - data.keys()
        if missing:
            raise ValueError(f"query_plan missing required fields: {', '.join(sorted(missing))}")
        for field_name in REQUIRED_QUERY_PLAN_FIELDS - {"intent"}:
            if not isinstance(data.get(field_name), list):
                raise ValueError(f"query_plan.{field_name} must be a list")
        if not isinstance(data.get("intent"), str):
            raise ValueError("query_plan.intent must be a string")
        return cls(
            intent=data["intent"],
            positive_terms=[str(item) for item in data["positive_terms"]],
            negative_terms=[str(item) for item in data["negative_terms"]],
            likely_categories=[str(item) for item in data["likely_categories"]],
            likely_interfaces=[str(item) for item in data["likely_interfaces"]],
            required_features=[str(item) for item in data["required_features"]],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "positive_terms": self.positive_terms,
            "negative_terms": self.negative_terms,
            "likely_categories": self.likely_categories,
            "likely_interfaces": self.likely_interfaces,
            "required_features": self.required_features,
        }


@dataclass
class Candidate:
    name: str
    skill_dir: Path
    card_path: Path
    card: dict[str, Any]


@dataclass
class RankedSkill:
    name: str
    path: str
    score: int
    category: str
    interfaces: list[str]
    patterns: list[str]
    why_matched: list[str] = field(default_factory=list)
    penalties: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    adaptation_hints: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RankedSkill":
        return cls(
            name=str(data.get("name", "")),
            path=str(data.get("path", "")),
            score=int(data.get("score", 0)),
            category=str(data.get("category", "")),
            interfaces=[str(item) for item in data.get("interfaces", [])],
            patterns=[str(item) for item in data.get("patterns", [])],
            why_matched=[str(item) for item in data.get("why_matched", [])],
            penalties=[str(item) for item in data.get("penalties", [])],
            risks=[str(item) for item in data.get("risks", [])],
            adaptation_hints=[str(item) for item in data.get("adaptation_hints", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "score": self.score,
            "category": self.category,
            "interfaces": self.interfaces,
            "patterns": self.patterns,
            "why_matched": self.why_matched,
            "penalties": self.penalties,
            "risks": self.risks,
            "adaptation_hints": self.adaptation_hints,
        }
