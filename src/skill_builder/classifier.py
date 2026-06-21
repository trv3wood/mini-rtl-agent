from __future__ import annotations

from typing import Any

from src.utils.llm import ChatClient

from .models import ModuleInfo


REQUIRED_CLASSIFICATION_FIELDS = {"category", "interfaces", "patterns", "keywords"}


def classify(module: ModuleInfo, llm: ChatClient) -> ModuleInfo:
    payload = llm.complete_json(
        [
            {
                "role": "system",
                "content": (
                    "You classify extracted Verilog/SystemVerilog modules for an RTL skill library. "
                    "Return only JSON with exactly these fields: category, interfaces, patterns, keywords. "
                    "Each field except category must be a list of short strings. "
                    "Base the classification on the module name, ports, parameters, comments, states, and source excerpt."
                ),
            },
            {
                "role": "user",
                "content": module_context(module),
            },
        ],
        temperature=0.0,
    )
    classification = validate_classification(payload)
    module.category = classification["category"]
    module.interfaces = classification["interfaces"]
    module.patterns = classification["patterns"]
    module.keywords = classification["keywords"]
    return module


def module_context(module: ModuleInfo) -> str:
    ports = [
        {
            "name": port.name,
            "direction": port.direction,
            "width": port.width,
        }
        for port in module.ports
    ]
    params = [{"name": param.name, "default": param.default} for param in module.parameters]
    return str(
        {
            "name": module.name,
            "source_path": str(module.source_path),
            "parameters": params,
            "ports": ports,
            "comments": module.comments,
            "states": module.states,
            "source_excerpt": module.source_text[:4000],
        }
    )


def validate_classification(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RuntimeError("classification response must be a JSON object")
    missing = REQUIRED_CLASSIFICATION_FIELDS - payload.keys()
    if missing:
        raise RuntimeError(f"classification response missing fields: {', '.join(sorted(missing))}")
    category = payload["category"]
    if not isinstance(category, str) or not category:
        raise RuntimeError("classification.category must be a non-empty string")
    return {
        "category": category,
        "interfaces": require_string_list(payload, "interfaces"),
        "patterns": require_string_list(payload, "patterns"),
        "keywords": require_string_list(payload, "keywords"),
    }


def require_string_list(payload: dict[str, Any], field: str) -> list[str]:
    value = payload[field]
    if not isinstance(value, list):
        raise RuntimeError(f"classification.{field} must be a list")
    return [str(item) for item in value]
