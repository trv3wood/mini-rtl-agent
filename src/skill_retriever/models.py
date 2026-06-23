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
    module_info_path: Path
    module_info: dict[str, Any]
    readme_text: str = ""
    skill_spec: dict[str, Any] = field(default_factory=dict)
    skill_spec_text: str = ""
    adaptation: dict[str, Any] = field(default_factory=dict)


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
