from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.utils.llm import ChatClient, OpenAICompatibleLLM


DEFAULT_SKILLS_ROOT = Path("skills")


def load_skill_taxonomy(skills_root: Path = DEFAULT_SKILLS_ROOT) -> dict[str, list[str]]:
    index_path = skills_root / "index.json"
    if not index_path.exists():
        return {"categories": [], "interfaces": [], "skills": []}
    data = json.loads(index_path.read_text(encoding="utf-8"))
    categories = sorted({str(item.get("category", "")) for item in data if item.get("category")})
    interfaces = sorted({str(interface) for item in data for interface in item.get("interfaces", [])})
    skills = sorted({str(item.get("name", "")) for item in data if item.get("name")})
    return {"categories": categories, "interfaces": interfaces, "skills": skills}


def annotate_architecture_skills(
    architecture: dict[str, Any],
    *,
    llm: ChatClient | None = None,
    skills_root: Path = DEFAULT_SKILLS_ROOT,
) -> dict[str, Any]:
    active_llm = llm or OpenAICompatibleLLM()
    taxonomy = load_skill_taxonomy(skills_root)
    payload = active_llm.complete_json(
        [
            {
                "role": "system",
                "content": (
                    "You are a skill mapper for RTL architecture nodes. "
                    "Map each submodule to one skill_category using the available skill taxonomy when possible. "
                    "Return only JSON with this shape: "
                    "{\"mappings\":[{\"name\":\"exact submodule name\",\"skill_category\":\"category\",\"why\":\"short reason\"}]}. "
                    "Use exact submodule names from the input. Use custom only when no taxonomy entry fits."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "skill_taxonomy": taxonomy,
                        "submodules": architecture.get("submodules", []),
                    },
                    indent=2,
                ),
            },
        ],
        temperature=0.0,
    )
    mapping = validate_skill_mapping(payload, [str(item["name"]) for item in architecture["submodules"]])
    annotated = dict(architecture)
    annotated["submodules"] = [
        {
            **submodule,
            "skill_category": mapping[submodule["name"]]["skill_category"],
            "skill_mapping_reason": mapping[submodule["name"]]["why"],
        }
        for submodule in architecture["submodules"]
    ]
    return annotated


def validate_skill_mapping(payload: dict[str, Any], submodule_names: list[str]) -> dict[str, dict[str, str]]:
    if not isinstance(payload, dict):
        raise RuntimeError("skill mapper response must be a JSON object")
    mappings = payload.get("mappings")
    if not isinstance(mappings, list):
        raise RuntimeError("skill mapper response missing mappings list")

    expected = set(submodule_names)
    by_name: dict[str, dict[str, str]] = {}
    for index, item in enumerate(mappings):
        if not isinstance(item, dict):
            raise RuntimeError(f"skill mapper mappings[{index}] must be an object")
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise RuntimeError(f"skill mapper mappings[{index}].name must be a non-empty string")
        if name not in expected:
            raise RuntimeError(f"skill mapper returned unknown submodule: {name}")
        skill_category = item.get("skill_category")
        if not isinstance(skill_category, str) or not skill_category:
            raise RuntimeError(f"skill mapper mappings[{index}].skill_category must be a non-empty string")
        by_name[name] = {
            "skill_category": skill_category,
            "why": str(item.get("why", "")),
        }

    missing = expected - by_name.keys()
    if missing:
        raise RuntimeError(f"skill mapper missing submodules: {', '.join(sorted(missing))}")
    return by_name
