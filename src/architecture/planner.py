from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.utils.llm import ChatClient, OpenAICompatibleLLM

from .mermaid import generate_mermaid
from .skill_mapper import annotate_architecture_skills
from .spec_generator import generate_architecture_markdown, write_module_specs


DEFAULT_OUTPUT_DIR = Path("work/architecture")

REQUIRED_ARCHITECTURE_FIELDS = {"top_module", "submodules", "connections", "notes"}
REQUIRED_SUBMODULE_FIELDS = {
    "name",
    "purpose",
    "inputs",
    "outputs",
    "constraints",
    "dependencies",
    "patterns",
}
REQUIRED_CONNECTION_FIELDS = {"from", "to"}


def plan_architecture(requirement: str, *, llm: ChatClient | None = None) -> dict[str, Any]:
    active_llm = llm or OpenAICompatibleLLM()
    payload = active_llm.complete_json(
        [
            {
                "role": "system",
                "content": (
                    "You are an architecture planner for RTL systems. "
                    "Given a natural-language hardware requirement, decompose it into major RTL submodules, "
                    "dependencies, and data/control connections. "
                    "Return only a JSON object with exactly these top-level fields: "
                    "top_module, submodules, connections, notes. "
                    "Each submodule must include: name, purpose, inputs, outputs, constraints, dependencies, patterns. "
                    "Each connection must include: from, to, signal. "
                    "Use concise RTL-style module names without spaces. "
                    "Do not emit RTL code."
                ),
            },
            {"role": "user", "content": requirement},
        ],
        temperature=0.1,
    )
    architecture = validate_architecture(payload)
    return annotate_architecture_skills(architecture, llm=active_llm)


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
    if not isinstance(payload, dict):
        raise RuntimeError("architecture planner response must be a JSON object")
    missing = REQUIRED_ARCHITECTURE_FIELDS - payload.keys()
    if missing:
        raise RuntimeError(f"architecture response missing fields: {', '.join(sorted(missing))}")
    top_module = payload["top_module"]
    if not isinstance(top_module, str) or not top_module.strip():
        raise RuntimeError("architecture.top_module must be a non-empty string")

    submodules = payload["submodules"]
    if not isinstance(submodules, list) or not submodules:
        raise RuntimeError("architecture.submodules must be a non-empty list")
    normalized_submodules = [validate_submodule(item, index) for index, item in enumerate(submodules)]
    known_names = {item["name"] for item in normalized_submodules}

    connections = payload["connections"]
    if not isinstance(connections, list):
        raise RuntimeError("architecture.connections must be a list")
    normalized_connections = [
        validate_connection(item, index, known_names) for index, item in enumerate(connections)
    ]

    notes = payload["notes"]
    if not isinstance(notes, list):
        raise RuntimeError("architecture.notes must be a list")

    return {
        "top_module": top_module.strip(),
        "submodules": normalized_submodules,
        "connections": normalized_connections,
        "notes": [str(item) for item in notes],
    }


def validate_submodule(item: Any, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise RuntimeError(f"architecture.submodules[{index}] must be an object")
    missing = REQUIRED_SUBMODULE_FIELDS - item.keys()
    if missing:
        raise RuntimeError(
            f"architecture.submodules[{index}] missing fields: {', '.join(sorted(missing))}"
        )
    name = item["name"]
    if not isinstance(name, str) or not name.strip():
        raise RuntimeError(f"architecture.submodules[{index}].name must be a non-empty string")
    return {
        "name": name.strip(),
        "purpose": require_string(item, "purpose", f"architecture.submodules[{index}]"),
        "inputs": require_string_list(item, "inputs", f"architecture.submodules[{index}]"),
        "outputs": require_string_list(item, "outputs", f"architecture.submodules[{index}]"),
        "constraints": require_string_list(item, "constraints", f"architecture.submodules[{index}]"),
        "dependencies": require_string_list(item, "dependencies", f"architecture.submodules[{index}]"),
        "patterns": require_string_list(item, "patterns", f"architecture.submodules[{index}]"),
    }


def validate_connection(item: Any, index: int, known_names: set[str]) -> dict[str, str]:
    if not isinstance(item, dict):
        raise RuntimeError(f"architecture.connections[{index}] must be an object")
    missing = REQUIRED_CONNECTION_FIELDS - item.keys()
    if missing:
        raise RuntimeError(
            f"architecture.connections[{index}] missing fields: {', '.join(sorted(missing))}"
        )
    source = require_string(item, "from", f"architecture.connections[{index}]")
    target = require_string(item, "to", f"architecture.connections[{index}]")
    if source not in known_names:
        raise RuntimeError(f"architecture.connections[{index}].from unknown submodule: {source}")
    if target not in known_names:
        raise RuntimeError(f"architecture.connections[{index}].to unknown submodule: {target}")
    return {
        "from": source,
        "to": target,
        "signal": str(item.get("signal", item.get("purpose", ""))),
    }


def require_string(item: dict[str, Any], field: str, path: str) -> str:
    value = item[field]
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{path}.{field} must be a non-empty string")
    return value.strip()


def require_string_list(item: dict[str, Any], field: str, path: str) -> list[str]:
    value = item[field]
    if not isinstance(value, list):
        raise RuntimeError(f"{path}.{field} must be a list")
    return [str(entry) for entry in value]
