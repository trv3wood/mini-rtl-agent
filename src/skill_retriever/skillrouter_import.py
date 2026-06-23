from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .models import RankedSkill
from .retriever import load_candidate, score_candidate
from .models import QueryPlan


def load_skillrouter_ids(retrieval_json: Path, task_id: str) -> list[str]:
    try:
        payload = json.loads(retrieval_json.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"SkillRouter retrieval file not found or unreadable: {retrieval_json}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid SkillRouter retrieval JSON: {exc}") from exc
    ids = payload.get(task_id)
    if ids is None:
        raise ValueError(f"task_id not found in SkillRouter retrieval JSON: {task_id}")
    if not isinstance(ids, list):
        raise ValueError(f"SkillRouter retrieval entry for {task_id} must be a list")
    return [str(item) for item in ids]


def skill_id_index(skills_root: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for module_info_path in sorted(skills_root.rglob("module_info.json")):
        candidate = load_candidate(module_info_path)
        if candidate is None:
            continue
        index[candidate.name] = module_info_path
        index[module_info_path.parent.name] = module_info_path
        skill_spec_id = candidate.skill_spec.get("skill_id")
        if skill_spec_id:
            index[str(skill_spec_id)] = module_info_path
    return index


def import_skillrouter_results(
    retrieval_json: Path,
    task_id: str,
    skills_root: Path,
    plan: QueryPlan,
    limit: int = 10,
) -> list[RankedSkill]:
    ids = load_skillrouter_ids(retrieval_json, task_id)
    index = skill_id_index(skills_root)
    results: list[RankedSkill] = []
    for rank, skill_id in enumerate(ids, start=1):
        path = index.get(skill_id)
        if path is None:
            continue
        candidate = load_candidate(path)
        if candidate is None:
            continue
        ranked = score_candidate(candidate, plan)
        semantic_bonus = max(1, 120 - rank * 5)
        results.append(
            replace(
                ranked,
                score=ranked.score + semantic_bonus,
                why_matched=[f"external SkillRouter rank {rank}: {skill_id}", *ranked.why_matched],
            )
        )
    results.sort(key=lambda item: (-item.score, item.name, item.path))
    return results[:limit]


def fuse_rankings(
    lexical: list[RankedSkill],
    semantic: list[RankedSkill],
    limit: int = 10,
) -> list[RankedSkill]:
    merged: dict[str, RankedSkill] = {item.name: item for item in lexical}
    for item in semantic:
        existing = merged.get(item.name)
        if existing is None:
            merged[item.name] = item
            continue
        merged[item.name] = replace(
            existing,
            score=existing.score + item.score,
            why_matched=dedupe([*item.why_matched, *existing.why_matched])[:12],
            penalties=dedupe([*existing.penalties, *item.penalties]),
            risks=dedupe([*existing.risks, *item.risks])[:8],
            adaptation_hints=dedupe([*existing.adaptation_hints, *item.adaptation_hints])[:8],
        )
    fused = list(merged.values())
    fused.sort(key=lambda item: (-item.score, item.name, item.path))
    return fused[:limit]


def fused_payload(plan: QueryPlan, lexical: list[RankedSkill], semantic: list[RankedSkill], fused: list[RankedSkill]) -> dict[str, Any]:
    return {
        "query_plan": plan.to_dict(),
        "lexical_results": [item.to_dict() for item in lexical],
        "semantic_results": [item.to_dict() for item in semantic],
        "results": [item.to_dict() for item in fused],
    }


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
