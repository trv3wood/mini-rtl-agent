from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, Field
from src.utils.llm import ChatClient

from .models import ModuleInfo


CLASSIFICATION_SCHEMA_VERSION = "module-analysis-v2"
SOURCE_EXCERPT_CHARS = 1200
MAX_PORTS_IN_PROMPT = 48
MAX_PARAMS_IN_PROMPT = 32
MAX_COMMENTS_IN_PROMPT = 8


class ModuleClassification(BaseModel):
    category: str = Field(min_length=1)
    interfaces: list[str]
    patterns: list[str]
    keywords: list[str]
    functional_summary: str = Field(min_length=20)
    structural_summary: str = Field(min_length=20)
    behavior_summary: str = Field(min_length=20)
    integration_notes: list[str]
    limitations: list[str]
    use_cases: list[str]


def classify(module: ModuleInfo, llm: ChatClient, cache_dir: Path | None = None) -> ModuleInfo:
    cache_path = classification_cache_path(module, cache_dir)
    if cache_path is not None and cache_path.exists():
        classification = ModuleClassification.model_validate_json(cache_path.read_text(encoding="utf-8"))
        apply_classification(module, classification)
        return module

    classification = llm.complete_structured(
        [
            {
                "role": "system",
                "content": (
                    "You analyze extracted Verilog/SystemVerilog modules for an RTL skill library. "
                    "Return both taxonomy labels and concise, module-specific engineering descriptions. "
                    "Avoid generic filler such as 'auto-generated skill', 'preserves the interface', or 'review before use'. "
                    "Base the answer on module name, ports, parameters, comments, states, and source excerpt. "
                    "If evidence is weak, say what is inferred from the interface rather than inventing behavior."
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
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_path.with_name(f".{cache_path.name}.tmp")
        tmp.write_text(classification.model_dump_json(indent=2) + "\n", encoding="utf-8")
        tmp.replace(cache_path)
    apply_classification(module, classification)
    return module


def apply_classification(module: ModuleInfo, classification: ModuleClassification) -> None:
    module.category = classification.category
    module.interfaces = classification.interfaces
    module.patterns = classification.patterns
    module.keywords = classification.keywords
    module.functional_summary = classification.functional_summary
    module.structural_summary = classification.structural_summary
    module.behavior_summary = classification.behavior_summary
    module.integration_notes = classification.integration_notes
    module.limitations = classification.limitations
    module.use_cases = classification.use_cases


def module_context(module: ModuleInfo) -> str:
    ports = [
        {
            "name": port.name,
            "direction": port.direction,
            "width": port.width,
        }
        for port in module.ports[:MAX_PORTS_IN_PROMPT]
    ]
    params = [{"name": param.name, "default": param.default} for param in module.parameters[:MAX_PARAMS_IN_PROMPT]]
    context = {
        "schema_version": CLASSIFICATION_SCHEMA_VERSION,
        "instructions": {
            "functional_summary": "Explain what the RTL block does in one or two module-specific sentences.",
            "structural_summary": "Describe internal organization from evidence: submodules, FIFO/register/FSM/counter/pipeline structure, or say inferred from interface.",
            "behavior_summary": "Describe handshake, buffering, routing, frame, reset, or state behavior visible from evidence.",
            "avoid": "Do not describe the generated template; describe the source RTL module.",
        },
        "name": module.name,
        "source_path": str(module.source_path),
        "parameter_count": len(module.parameters),
        "port_count": len(module.ports),
        "parameters": params,
        "ports": ports,
        "comments": module.comments[:MAX_COMMENTS_IN_PROMPT],
        "states": module.states,
        "source_excerpt": compact_source_excerpt(module.source_text),
    }
    return json.dumps(context, ensure_ascii=True, sort_keys=True)


def compact_source_excerpt(source_text: str) -> str:
    lines = []
    for line in source_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("//"):
            continue
        lines.append(stripped)
        if sum(len(item) + 1 for item in lines) >= SOURCE_EXCERPT_CHARS:
            break
    return "\n".join(lines)[:SOURCE_EXCERPT_CHARS]


def classification_cache_path(module: ModuleInfo, cache_dir: Path | None) -> Path | None:
    if cache_dir is None:
        return None
    payload = json.dumps(
        {
            "schema_version": CLASSIFICATION_SCHEMA_VERSION,
            "name": module.name,
            "source_path": str(module.source_path),
            "parameters": [{"name": param.name, "default": param.default} for param in module.parameters],
            "ports": [{"name": port.name, "direction": port.direction, "width": port.width} for port in module.ports],
            "comments": module.comments,
            "states": module.states,
            "source_excerpt": compact_source_excerpt(module.source_text),
        },
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return cache_dir / f"{module.name}_{digest[:16]}.json"


def validate_classification(payload: dict) -> dict:
    return ModuleClassification.model_validate(payload).model_dump()
