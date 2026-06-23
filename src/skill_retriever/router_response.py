from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import QueryPlan, RankedSkill
from .retriever import flatten


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
    for relative in ("rtl/root_module.sv", "rtl/root_module.v", "template.v"):
        candidate = skill_dir / relative
        if candidate.exists():
            return candidate.as_posix()
    rtl_dir = skill_dir / "rtl"
    if rtl_dir.exists():
        for suffix in ("*.sv", "*.v"):
            matches = sorted(rtl_dir.glob(suffix))
            if matches:
                return matches[0].as_posix()
    module_info_path = skill_dir / "module_info.json"
    if module_info_path.exists():
        try:
            module_info = json.loads(module_info_path.read_text(encoding="utf-8"))
        except Exception:
            module_info = {}
        source_refs = module_info.get("source_refs")
        if isinstance(source_refs, list) and source_refs:
            first = source_refs[0]
            if isinstance(first, dict) and first.get("path"):
                return str(first["path"])
        for item in flatten(module_info.get("source_files")):
            if str(item).strip():
                return str(item)
    return skill.path


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
