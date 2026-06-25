from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .models import Candidate, QueryPlan, RankedSkill


STRUCTURED_FIELDS = (
    "core_function",
    "algorithm",
    "structure",
    "keywords",
    "retrieval_text",
)


def normalize(text: str) -> str:
    return text.lower().replace("_", " ")


def flatten(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(flatten(item))
        return out
    if isinstance(value, dict):
        out = []
        for key, item in value.items():
            out.append(str(key))
            out.extend(flatten(item))
        return out
    return [str(value)]


def rg_matching_module_infos(skills_root: Path, positive_terms: list[str]) -> set[Path]:
    matched: set[Path] = set()
    if not skills_root.exists():
        return matched
    rg = shutil.which("rg")
    for term in positive_terms:
        term = term.strip()
        if not term:
            continue
        if rg:
            run = subprocess.run(
                [
                    rg,
                    "-i",
                    "-l",
                    "--glob",
                    "compact_card.json",
                    term,
                    str(skills_root),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            for line in run.stdout.splitlines():
                path = Path(line)
                if path.name == "compact_card.json":
                    matched.add(path)
        else:
            needle = normalize(term)
            for path in skills_root.rglob("compact_card.json"):
                text = path.read_text(encoding="utf-8", errors="ignore")
                if needle not in normalize(text):
                    continue
                matched.add(path)
    if not matched:
        matched = set(skills_root.rglob("compact_card.json"))
    return matched


def candidate_metadata_path(skill_dir: Path) -> Path | None:
    path = skill_dir / "compact_card.json"
    return path if path.exists() else None


def load_candidate(path: Path) -> Candidate | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if path.name != "compact_card.json":
        return None
    module_info = module_info_from_compact_card(payload)
    return Candidate(
        name=str(module_info.get("name") or path.parent.name),
        skill_dir=path.parent,
        card_path=path,
        card=module_info,
    )


def module_info_from_compact_card(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": card.get("name"),
        "category": card.get("granularity") or "",
        "core_function": card.get("core_function") or "",
        "algorithm": card.get("algorithm") or "",
        "interfaces": interface_terms(card.get("interface_signature")),
        "patterns": card.get("structure") or [],
        "structure": card.get("structure") or [],
        "keywords": card.get("keywords", []),
        "retrieval_text": card.get("retrieval_text", ""),
    }


def interface_terms(signature: Any) -> list[str]:
    terms: list[str] = []
    for value in flatten(signature):
        for part in re_split_interface(str(value)):
            if part:
                terms.append(part)
    return dedupe(terms)


def re_split_interface(value: str) -> list[str]:
    return [part.strip() for part in value.replace("->", ",").split(",")]


def field_texts(module_info: dict[str, Any]) -> dict[str, str]:
    return {
        field: normalize(" ".join(flatten(module_info.get(field))))
        for field in STRUCTURED_FIELDS
    }


def score_candidate(candidate: Candidate, plan: QueryPlan) -> RankedSkill:
    card = candidate.card
    texts = field_texts(card)
    category = str(card.get("category", ""))
    interfaces = [str(item) for item in card.get("interfaces", [])]
    patterns = [str(item) for item in card.get("patterns", [])]

    score = 0
    why: list[str] = []
    penalties: list[str] = []

    for term in plan.positive_terms:
        needle = normalize(term)
        if not needle:
            continue
        hits = [field for field, text in texts.items() if needle in text]
        if hits:
            score += min(18, 5 * len(hits))
            why.append(f"term '{term}' matched compact_card fields: {', '.join(hits)}")

    for feature in plan.required_features:
        needle = normalize(feature)
        if any(needle in text for text in texts.values()):
            score += 12
            why.append(f"required feature matched: {feature}")

    for term in plan.negative_terms:
        needle = normalize(term)
        if any(needle in text for text in texts.values()):
            score -= 20
            penalties.append(f"negative term matched: {term}")

    return RankedSkill(
        name=candidate.name,
        path=str(candidate.skill_dir),
        score=max(score, 0),
        category=category,
        interfaces=interfaces,
        patterns=patterns,
        why_matched=why[:12],
        penalties=penalties,
        risks=[],
        adaptation_hints=[],
    )


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def retrieve_skills(plan: QueryPlan, skills_root: Path, limit: int = 10) -> list[RankedSkill]:
    card_paths = sorted(rg_matching_module_infos(skills_root, plan.positive_terms))
    candidates = [candidate for path in card_paths if (candidate := load_candidate(path))]
    ranked = [score_candidate(candidate, plan) for candidate in candidates]
    ranked.sort(key=lambda item: (-item.score, item.name, item.path))
    return ranked[:limit]
