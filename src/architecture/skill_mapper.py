from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from src.utils.llm import ChatClient, OpenAICompatibleLLM


DEFAULT_SKILLS_ROOT = Path("skills")


class SkillMapping(BaseModel):
    name: str = Field(min_length=1)
    skill_category: str = Field(min_length=1)
    why: str = ""


class SkillMappingResponse(BaseModel):
    mappings: list[SkillMapping]

    def to_mapping_dict(self, submodule_names: list[str]) -> dict[str, dict[str, str]]:
        expected = set(submodule_names)
        by_name = {
            item.name: {
                "skill_category": item.skill_category,
                "why": item.why,
            }
            for item in self.mappings
        }
        unknown = set(by_name) - expected
        if unknown:
            raise ValueError(f"skill mapper returned unknown submodules: {', '.join(sorted(unknown))}")
        missing = expected - set(by_name)
        if missing:
            raise ValueError(f"skill mapper missing submodules: {', '.join(sorted(missing))}")
        return by_name


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
    response = active_llm.complete_structured(
        [
            {
                "role": "system",
                "content": (
                    "You are a skill mapper for RTL architecture nodes. "
                    "Map each submodule to one skill_category using the available skill taxonomy when possible. "
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
        SkillMappingResponse,
        temperature=0.0,
    )
    mapping = response.to_mapping_dict([str(item["name"]) for item in architecture["submodules"]])
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
    return SkillMappingResponse.model_validate(payload).to_mapping_dict(submodule_names)
