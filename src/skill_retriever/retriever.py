from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .models import Candidate, QueryPlan, RankedSkill


STRUCTURED_FIELDS = (
    "category",
    "interfaces",
    "patterns",
    "ports",
    "parameters",
    "constraints",
    "keywords",
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
                    "module_info.json",
                    "--glob",
                    "README.md",
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
                if path.name == "module_info.json":
                    matched.add(path)
                elif path.name == "README.md":
                    module_info = path.parent / "module_info.json"
                    if module_info.exists():
                        matched.add(module_info)
        else:
            needle = normalize(term)
            for path in list(skills_root.rglob("module_info.json")) + list(skills_root.rglob("README.md")):
                text = path.read_text(encoding="utf-8", errors="ignore")
                if needle in normalize(text):
                    matched.add(path if path.name == "module_info.json" else path.parent / "module_info.json")
    if not matched:
        matched = set(skills_root.rglob("module_info.json"))
    return matched


def load_candidate(path: Path) -> Candidate | None:
    try:
        module_info = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    readme_path = path.parent / "README.md"
    readme_text = readme_path.read_text(encoding="utf-8", errors="ignore") if readme_path.exists() else ""
    return Candidate(
        name=str(module_info.get("name") or path.parent.name),
        skill_dir=path.parent,
        module_info_path=path,
        module_info=module_info,
        readme_text=readme_text,
    )


def field_texts(module_info: dict[str, Any]) -> dict[str, str]:
    return {
        field: normalize(" ".join(flatten(module_info.get(field))))
        for field in STRUCTURED_FIELDS
    }


def score_candidate(candidate: Candidate, plan: QueryPlan) -> RankedSkill:
    module_info = candidate.module_info
    texts = field_texts(module_info)
    readme_text = normalize(candidate.readme_text)
    category = str(module_info.get("category", ""))
    interfaces = [str(item) for item in module_info.get("interfaces", [])]
    patterns = [str(item) for item in module_info.get("patterns", [])]

    score = 0
    why: list[str] = []
    penalties: list[str] = []

    if normalize(category) in {normalize(item) for item in plan.likely_categories}:
        score += 18
        why.append(f"category matched: {category}")

    interface_hits = [
        item for item in plan.likely_interfaces if normalize(item) in {normalize(i) for i in interfaces}
    ]
    if interface_hits:
        score += 14 * len(interface_hits)
        why.append(f"interfaces matched: {', '.join(interface_hits)}")

    for term in plan.positive_terms:
        needle = normalize(term)
        if not needle:
            continue
        hits = [field for field, text in texts.items() if needle in text]
        if hits:
            score += min(18, 5 * len(hits))
            why.append(f"term '{term}' matched structured fields: {', '.join(hits)}")
        elif needle in readme_text:
            score += 3
            why.append(f"term '{term}' matched README")

    for feature in plan.required_features:
        needle = normalize(feature)
        if any(needle in text for text in texts.values()) or needle in readme_text:
            score += 12
            why.append(f"required feature matched: {feature}")

    for term in plan.negative_terms:
        needle = normalize(term)
        if any(needle in text for text in texts.values()) or needle in readme_text:
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
    )


def retrieve_skills(plan: QueryPlan, skills_root: Path, limit: int = 10) -> list[RankedSkill]:
    module_info_paths = sorted(rg_matching_module_infos(skills_root, plan.positive_terms))
    candidates = [candidate for path in module_info_paths if (candidate := load_candidate(path))]
    ranked = [score_candidate(candidate, plan) for candidate in candidates]
    ranked.sort(key=lambda item: (-item.score, item.name, item.path))
    return ranked[:limit]

