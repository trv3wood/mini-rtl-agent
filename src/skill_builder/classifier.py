from __future__ import annotations

from pydantic import BaseModel, Field
from src.utils.llm import ChatClient

from .models import ModuleInfo


class ModuleClassification(BaseModel):
    category: str = Field(min_length=1)
    interfaces: list[str]
    patterns: list[str]
    keywords: list[str]


def classify(module: ModuleInfo, llm: ChatClient) -> ModuleInfo:
    classification = llm.complete_structured(
        [
            {
                "role": "system",
                "content": (
                    "You classify extracted Verilog/SystemVerilog modules for an RTL skill library. "
                    "Base the classification on the module name, ports, parameters, comments, states, and source excerpt."
                ),
            },
            {
                "role": "user",
                "content": module_context(module),
            },
        ],
        ModuleClassification,
        temperature=0.0,
    )
    module.category = classification.category
    module.interfaces = classification.interfaces
    module.patterns = classification.patterns
    module.keywords = classification.keywords
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


def validate_classification(payload: dict) -> dict:
    return ModuleClassification.model_validate(payload).model_dump()
