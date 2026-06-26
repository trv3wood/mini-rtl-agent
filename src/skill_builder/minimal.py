from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from .models import ModuleInfo, SkillCandidate
from .semantic import make_compact_card_from_skill


REQUIRED_SKILL_FIELDS = {
    "skill_id",
    "name",
    "granularity",
    "project",
    "core_function",
    "algorithm",
    "interface",
    "structure",
    "parameters",
    "dependencies",
    "used_by",
    "rtl_files",
}
REQUIRED_CARD_FIELDS = {
    "skill_id",
    "name",
    "core_function",
    "algorithm",
    "structure",
    "interface_signature",
    "granularity",
    "project",
    "keywords",
    "retrieval_text",
}


def build_minimal_skill_json(
    module: ModuleInfo,
    candidate: SkillCandidate,
    repo_path: Path,
    rtl_files: list[str],
    semantic_skill: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if semantic_skill is None:
        semantic_skill = {}

    skill_json: dict[str, Any] = {
        "skill_id": candidate.skill_id,
        "name": module.name,
        "granularity": semantic_skill.get("granularity", granularity(candidate)),
        "project": repo_path.name,
        "core_function": semantic_skill.get(
            "core_function",
            short_text(fallback_core_function(module), 18),
        ),
        "algorithm": semantic_skill.get(
            "algorithm",
            short_text(fallback_algorithm(module), 16),
        ),
        "interface": semantic_skill.get(
            "interface",
            interface_json(module),
        ),
        "structure": compact_list(
            semantic_skill.get(
                "structure",
                module.patterns or module.states or ["rtl module"],
            ),
            4,
        ),
        "parameters": [param.name for param in module.parameters],
        "dependencies": candidate.dependency_modules,
        "used_by": [],
        "rtl_files": rtl_files,
    }

    keywords = semantic_skill.get("keywords", [])
    if not keywords:
        keywords = keyword_candidates(module, skill_json)
    skill_json["keywords"] = compact_list(keywords, 10)

    return skill_json


def build_compact_card(skill_json: dict[str, Any]) -> dict[str, Any]:
    return make_compact_card_from_skill(skill_json)


def keyword_candidates(module: ModuleInfo, skill: dict[str, Any]) -> list[str]:
    items: list[str] = []
    items.extend(module.keywords)
    items.extend(module.interfaces)
    items.extend(split_identifier(module.name))
    for name in skill.get("parameters", []):
        items.extend(split_identifier(name))
    for port in module.ports:
        items.extend(split_identifier(port.name))
    items.extend(skill.get("structure", []))
    return items


def validate_minimal_skill(skill: dict[str, Any]) -> list[str]:
    errors = []
    missing = REQUIRED_SKILL_FIELDS - skill.keys()
    if missing:
        errors.append(f"skill.json missing fields: {', '.join(sorted(missing))}")
    extra = skill.keys() - REQUIRED_SKILL_FIELDS - {"keywords"}
    if extra:
        errors.append(f"skill.json unknown fields: {', '.join(sorted(extra))}")
    if skill.get("granularity") not in {"leaf", "primitive", "composite"}:
        errors.append("skill.json.granularity must be leaf, primitive, or composite")
    if not isinstance(skill.get("rtl_files"), list) or not skill.get("rtl_files"):
        errors.append("skill.json.rtl_files must be a non-empty list")
    if len(skill.get("structure", [])) > 4:
        errors.append("skill.json.structure must contain at most 4 items")
    return errors


def validate_compact_card(card: dict[str, Any]) -> list[str]:
    errors = []
    missing = REQUIRED_CARD_FIELDS - card.keys()
    if missing:
        errors.append(f"compact_card.json missing fields: {', '.join(sorted(missing))}")
    extra = card.keys() - REQUIRED_CARD_FIELDS
    if extra:
        errors.append(f"compact_card.json unknown fields: {', '.join(sorted(extra))}")
    if len(card.get("keywords", [])) > 10:
        errors.append("compact_card.json.keywords must contain at most 10 items")
    if len(set(card.get("keywords", []))) != len(card.get("keywords", [])):
        errors.append("compact_card.json.keywords must not contain duplicates")
    if len(card.get("structure", [])) > 4:
        errors.append("compact_card.json.structure must contain at most 4 items")
    if len(set(card.get("structure", []))) != len(card.get("structure", [])):
        errors.append("compact_card.json.structure must not contain duplicates")
    if word_count(str(card.get("retrieval_text", ""))) > 60:
        errors.append("compact_card.json.retrieval_text must be at most 60 words")
    return errors


def copy_minimal_rtl(candidate: SkillCandidate, skill_dir: Path, repo_path: Path) -> list[str]:
    rtl_files = []
    seen: set[str] = set()
    for source_file in candidate.source_files:
        source = Path(source_file)
        relative = minimal_rtl_relative(source_file, repo_path)
        if relative in seen:
            raise ValueError(f"duplicate RTL output path in skill package: {relative}")
        seen.add(relative)
        destination = skill_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        rtl_files.append(relative)
    return rtl_files


def minimal_rtl_relative(source_file: str, repo_path: Path) -> str:
    source = Path(source_file).resolve()
    return f"rtl/{source.name}"


def granularity(candidate: SkillCandidate) -> str:
    if candidate.dependency_modules:
        return "composite"
    if candidate.candidate_kind == "internal":
        return "leaf"
    return "primitive"


def interface_json(module: ModuleInfo) -> dict[str, str]:
    if module.interfaces:
        signature = ", ".join(compact_list(module.interfaces, 3))
        return {"input": signature, "output": signature}
    inputs = [port.name for port in module.ports if port.direction == "input"]
    outputs = [port.name for port in module.ports if port.direction == "output"]
    return {
        "input": short_text(", ".join(inputs) or "none", 8),
        "output": short_text(", ".join(outputs) or "none", 8),
    }


def interface_signature(interface: dict[str, str]) -> str:
    left = interface.get("input", "unknown")
    right = interface.get("output", "unknown")
    if left == right:
        return left
    return f"{left} -> {right}"


def fallback_core_function(module: ModuleInfo) -> str:
    if module.interfaces:
        return f"{module.name} {module.interfaces[0]} RTL block"
    return f"{module.name} RTL block"


def fallback_algorithm(module: ModuleInfo) -> str:
    if module.patterns:
        return module.patterns[0]
    if module.states:
        return f"state logic over {module.states[0]}"
    return "module-specific RTL logic"


def compact_list(items: list[str], limit: int) -> list[str]:
    seen = set()
    out = []
    for item in items:
        normalized = normalize_token(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
        if len(out) >= limit:
            break
    return out


def split_identifier(text: str) -> list[str]:
    return [part for part in re.split(r"[^A-Za-z0-9]+", str(text)) if part]


def short_text(text: str, max_words: int) -> str:
    words = re.findall(r"\S+", " ".join(text.split()))
    return " ".join(words[:max_words])


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def normalize_token(text: str) -> str:
    return " ".join(str(text).strip().split())
