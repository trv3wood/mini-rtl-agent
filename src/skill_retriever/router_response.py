from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import QueryPlan, RankedSkill
from .backends.rg_rerank.retriever import flatten


def build_router_response(
    plan: QueryPlan,
    ranked: list[RankedSkill],
    *,
    limit: int = 5,
) -> dict[str, Any]:
    selected = ranked[0] if ranked else None
    return {
        "query_plan": plan.to_dict(),
        "selected_skill": selected.name if selected else None,
        "candidate_skills": [item.name for item in ranked[:limit]],
        "matched_capabilities": matched_capabilities(selected) if selected else [],
        "required_adaptations": selected.adaptation_hints if selected else [],
        "risks": selected_risks(selected) if selected else ["no matching skill found"],
        "source_path": source_path(selected) if selected else None,
        "results": [item.to_dict() for item in ranked[:limit]],
    }


def matched_capabilities(skill: RankedSkill) -> list[str]:
    capabilities = []
    capabilities.extend(f"interface: {item}" for item in skill.interfaces)
    capabilities.extend(f"pattern: {item}" for item in skill.patterns[:4])
    capabilities.extend(skill.why_matched[:4])
    return dedupe(capabilities)


def selected_risks(skill: RankedSkill) -> list[str]:
    risks = [*skill.risks, *skill.penalties]
    return dedupe(risks)


def source_path(skill: RankedSkill) -> str | None:
    skill_dir = Path(skill.path)
    skill_json_path = skill_dir / "skill.json"
    if skill_json_path.exists():
        try:
            skill_json = json.loads(skill_json_path.read_text(encoding="utf-8"))
        except Exception:
            skill_json = {}
        for item in flatten(skill_json.get("rtl_files")):
            candidate = skill_dir / str(item)
            if candidate.exists():
                return candidate.as_posix()
    for relative in ("rtl/root_module.sv", "rtl/root_module.v"):
        candidate = skill_dir / relative
        if candidate.exists():
            return candidate.as_posix()
    rtl_dir = skill_dir / "rtl"
    if rtl_dir.exists():
        for suffix in ("*.sv", "*.v"):
            matches = sorted(rtl_dir.glob(suffix))
            if matches:
                return matches[0].as_posix()
    return skill.path


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
