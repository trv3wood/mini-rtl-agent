from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator
from src.utils.llm import ChatClient, OpenAICompatibleLLM

from .mermaid import generate_mermaid
from .skill_mapper import annotate_architecture_skills
from .spec_generator import generate_architecture_markdown, write_module_specs


DEFAULT_OUTPUT_DIR = Path("work/architecture")


class ArchitectureSubmodule(BaseModel):
    name: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    inputs: list[str]
    outputs: list[str]
    constraints: list[str]
    dependencies: list[str]
    patterns: list[str]


class ArchitectureConnection(BaseModel):
    source: str = Field(alias="from", min_length=1)
    target: str = Field(alias="to", min_length=1)
    signal: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "from": self.source,
            "to": self.target,
            "signal": self.signal,
        }


class ArchitecturePlan(BaseModel):
    top_module: str = Field(min_length=1)
    submodules: list[ArchitectureSubmodule] = Field(min_length=1)
    connections: list[ArchitectureConnection]
    notes: list[str]

    @model_validator(mode="after")
    def validate_connection_endpoints(self) -> "ArchitecturePlan":
        names = {item.name for item in self.submodules}
        for connection in self.connections:
            if connection.source not in names:
                raise ValueError(f"connection.from unknown submodule: {connection.source}")
            if connection.target not in names:
                raise ValueError(f"connection.to unknown submodule: {connection.target}")
        return self

    def to_architecture_dict(self) -> dict[str, Any]:
        return {
            "top_module": self.top_module,
            "submodules": [item.model_dump() for item in self.submodules],
            "connections": [item.to_dict() for item in self.connections],
            "notes": self.notes,
        }


def plan_architecture(requirement: str, *, llm: ChatClient | None = None) -> dict[str, Any]:
    active_llm = llm or OpenAICompatibleLLM()
    plan = active_llm.complete_structured(
        [
            {
                "role": "system",
                "content": (
                    "You are an architecture planner for RTL systems. "
                    "Given a natural-language hardware requirement, decompose it into major RTL submodules, "
                    "dependencies, and data/control connections. "
                    "Use concise RTL-style module names without spaces. "
                    "Do not emit RTL code."
                ),
            },
            {"role": "user", "content": requirement},
        ],
        ArchitecturePlan,
        temperature=0.1,
    )
    return annotate_architecture_skills(plan.to_architecture_dict(), llm=active_llm)


def write_architecture_outputs(
    requirement: str,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    llm: ChatClient | None = None,
) -> dict[str, Path | list[Path]]:
    architecture = plan_architecture(requirement, llm=llm)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "architecture.json"
    md_path = output_dir / "architecture.md"
    mmd_path = output_dir / "architecture.mmd"
    json_path.write_text(json.dumps(architecture, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(generate_architecture_markdown(requirement, architecture), encoding="utf-8")
    mmd_path.write_text(generate_mermaid(architecture), encoding="utf-8")
    spec_paths = write_module_specs(architecture, output_dir)
    return {
        "json": json_path,
        "markdown": md_path,
        "mermaid": mmd_path,
        "specs": spec_paths,
    }


def validate_architecture(payload: dict[str, Any]) -> dict[str, Any]:
    return ArchitecturePlan.model_validate(payload).to_architecture_dict()
