from __future__ import annotations

from dataclasses import field
from typing import Any, Protocol

from pydantic import BaseModel

from src.utils.llm import ChatClient, LLMConfig, OpenAICompatibleLLM


class SemanticAnnotation(BaseModel):
    """LLM-generated semantic fields for a skill."""

    core_function: str = ""
    algorithm: str = "unknown"
    structure: list[str] = field(default_factory=list)
    interface_protocol: str = "unknown"
    granularity: str = "primitive"
    keywords: list[str] = field(default_factory=list)


class AnnotationResult(BaseModel):
    annotation: SemanticAnnotation
    backend: str = "fallback"
    llm_used: bool = False
    warnings: list[str] = field(default_factory=list)


class SkillAnnotator(Protocol):
    def annotate(self, semantic_input: dict[str, Any]) -> AnnotationResult:
        ...


def create_annotator(config: LLMConfig | None = None) -> SkillAnnotator:
    try:
        client = OpenAICompatibleLLM(config or LLMConfig.from_env())
    except RuntimeError as exc:
        return FallbackAnnotator(warnings=[f"semantic annotation using rule-based fallback: {exc}"])
    return OpenAICompatibleAnnotator(client)


class OpenAICompatibleAnnotator:
    def __init__(self, client: ChatClient) -> None:
        self.client = client

    def annotate(self, semantic_input: dict[str, Any]) -> AnnotationResult:
        messages = [
            {"role": "system", "content": SEMANTIC_ANNOTATOR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Annotate the following RTL module with semantic fields. "
                    "Output only the JSON object. Do not invent facts.\n\n"
                    + _format_input(semantic_input)
                ),
            },
        ]

        try:
            result = self.client.complete_structured(messages, SemanticAnnotation, temperature=0.0)
            return AnnotationResult(
                annotation=result,
                backend="openai_compatible",
                llm_used=True,
                warnings=[],
            )
        except Exception as exc:
            return AnnotationResult(
                annotation=_fallback_annotation(semantic_input),
                backend="fallback",
                llm_used=False,
                warnings=[f"LLM annotation failed, using fallback: {exc}"],
            )


class FallbackAnnotator:
    def __init__(self, warnings: list[str] | None = None) -> None:
        self.warnings = warnings or ["semantic annotation using rule-based fallback"]

    def annotate(self, semantic_input: dict[str, Any]) -> AnnotationResult:
        return AnnotationResult(
            annotation=_fallback_annotation(semantic_input),
            backend="fallback",
            llm_used=False,
            warnings=list(self.warnings),
        )


def _fallback_annotation(semantic_input: dict[str, Any]) -> SemanticAnnotation:
    module_name = str(semantic_input.get("module", "unknown")).lower()
    ports = semantic_input.get("ports", [])
    parameters = semantic_input.get("parameters", [])
    dependencies = semantic_input.get("dependencies", [])
    structural = semantic_input.get("structural_facts", {})
    comments = semantic_input.get("comments", [])

    core_function = _fallback_core_function(module_name, ports, comments)
    algorithm = _fallback_algorithm(module_name, structural, parameters)
    structure = _fallback_structure(module_name, structural, dependencies)
    interface_protocol = _fallback_interface_protocol(module_name, ports)
    granularity = _fallback_granularity(semantic_input.get("candidate_kind", ""), dependencies)
    keywords = _fallback_keywords(module_name, ports, dependencies, parameters)

    return SemanticAnnotation(
        core_function=core_function,
        algorithm=algorithm,
        structure=structure,
        interface_protocol=interface_protocol,
        granularity=granularity,
        keywords=keywords,
    )


def _fallback_core_function(module_name: str, ports: list[dict], comments: list[str]) -> str:
    comment_text = " ".join(comments).lower()
    if "fifo" in module_name or "fifo" in comment_text:
        if "srl" in module_name or "shift" in comment_text:
            return "SRL-based shallow FIFO buffering"
        if "async" in module_name or "cdc" in comment_text:
            return "dual-clock asynchronous FIFO buffering"
        if "pipeline" in module_name:
            return "register-slice pipeline FIFO for timing"
        if "axis" in module_name:
            return "AXI-stream elastic FIFO buffering with occupancy tracking"
        return "FIFO buffering"
    if "arbiter" in module_name or "arb" in module_name:
        return "N-port request arbitration"
    if "adapter" in module_name:
        return "interface adaptation"
    if "uart" in module_name:
        if "tx" in module_name:
            return "UART transmit framing"
        if "rx" in module_name:
            return "UART receive sampling and framing"
        return "UART serial communication"
    if "i2c" in module_name:
        return "I2C bus master control"
    if "spi" in module_name:
        return "SPI master shift control"
    if "axis" in module_name:
        return "AXI-stream data path processing"
    if "wishbone" in module_name:
        return "Wishbone bus register block"
    if "reset" in module_name or "sync" in module_name:
        return "reset CDC synchronization"
    if "handshake" in module_name:
        return "ready-valid handshake buffering"
    return f"{module_name} RTL module"


def _fallback_algorithm(module_name: str, structural: dict, parameters: list[str]) -> str:
    param_lower = [p.lower() for p in parameters]
    if "round_robin" in param_lower or "round" in param_lower:
        return "masked round-robin arbitration"
    if "priority" in param_lower or "fixed" in param_lower:
        return "fixed-priority arbitration"
    if "gray" in param_lower:
        return "Gray-pointer crossing for dual-clock CDC"
    if "baud" in param_lower or "prescale" in param_lower:
        return "prescaled baud-rate timing"
    if "fifo" in module_name:
        return "circular buffer with read/write pointer management"
    if "adapter" in module_name:
        return "width conversion with handshake alignment"
    if "uart" in module_name:
        return "state-machine-driven serial frame encoding/decoding"
    if "spi" in module_name:
        return "shift-register serialization with configurable CPOL/CPHA"
    if "i2c" in module_name:
        return "START/STOP generation with ACK sampling"
    fsm = structural.get("fsm_candidates", [])
    if fsm:
        return f"state-machine control over {', '.join(fsm[:3])}"
    if structural.get("always_blocks", 0) > 0:
        return "combinational and sequential RTL logic"
    return "module-specific RTL logic"


def _fallback_structure(module_name: str, structural: dict, dependencies: list[str]) -> list[str]:
    parts: list[str] = []
    if structural.get("fsm_candidates"):
        parts.append("FSM controller")
    if structural.get("memory_candidates"):
        parts.append("explicit memory array")
    if structural.get("always_blocks", 0) > 0:
        parts.append("registered datapath")
    if structural.get("continuous_assignments", 0) > 0:
        parts.append("combinational decode")
    if dependencies:
        parts.append(f"sub-module integration: {', '.join(dependencies[:2])}")
    if "fifo" in module_name:
        if "read pointer" not in " ".join(parts).lower():
            parts.insert(0, "read/write pointer logic")
        if "circular buffer" not in " ".join(parts).lower():
            parts.insert(1, "circular buffer")
    if "arbiter" in module_name:
        parts.insert(0, "priority selection logic")
    if "adapter" in module_name:
        parts.insert(0, "data width adaptor logic")
    if not parts:
        parts.append("RTL module body")
    return parts[:4]


def _fallback_interface_protocol(module_name: str, ports: list[dict]) -> str:
    port_names = [p["name"].lower() for p in ports]
    if "valid" in port_names and "ready" in port_names:
        return "ready-valid handshake"
    if "wbs_" in " ".join(port_names) or "wbm_" in " ".join(port_names):
        return "Wishbone"
    if "scl" in port_names and "sda" in port_names:
        return "I2C"
    if "sclk" in port_names or "mosi" in port_names:
        return "SPI"
    if "tx" in port_names or "rx" in port_names:
        return "serial"
    if "request" in port_names and "grant" in port_names:
        return "request-grant"
    return "parallel"


def _fallback_granularity(candidate_kind: str, dependencies: list[str]) -> str:
    if candidate_kind == "internal":
        return "leaf"
    if candidate_kind == "composite" or dependencies:
        return "composite"
    if candidate_kind == "standalone":
        return "primitive"
    return "primitive"


def _fallback_keywords(
    module_name: str,
    ports: list[dict],
    dependencies: list[str],
    parameters: list[str],
) -> list[str]:
    keywords: list[str] = []
    lowered = module_name.lower()
    for token in lowered.replace("_", " ").split():
        if token not in keywords and len(token) > 1:
            keywords.append(token)
    for port in ports:
        name = port["name"].lower()
        for token in name.replace("_", " ").split():
            if token not in keywords and len(token) > 1:
                keywords.append(token)
    for dep in dependencies:
        for token in dep.lower().replace("_", " ").split():
            if token not in keywords and len(token) > 1:
                keywords.append(token)
    for param in parameters:
        for token in param.lower().replace("_", " ").split():
            if token not in keywords and len(token) > 1 and token not in {
                "clk", "freq", "baud", "width", "depth", "ports",
            }:
                keywords.append(token)
    return keywords[:10]


SEMANTIC_ANNOTATOR_SYSTEM_PROMPT = """\
You are an RTL Skill semantic annotator. Your role is to produce concise, accurate
semantic descriptions of hardware modules for retrieval and skill matching.

Rules:
1. Only use the facts provided in the input. Do NOT invent ports, parameters, or dependencies.
2. Output EXACTLY one JSON object with only the fields listed below. No extra text.
3. Every string field must be short: core_function ≤ 18 words, algorithm ≤ 16 words.
4. keywords: use short engineering terms only (e.g. "round_robin", "fifo", "arbiter",
   "handshake", "width_conversion"). ≤ 10 items.
5. structure: describe hardware structural elements (e.g. "priority encoder",
   "circular buffer", "FSM controller", "registered grant"). ≤ 4 items.
6. algorithm: describe the implementation method — choice, encoding, arbitration,
   buffering, synchronization, conversion, etc.
7. interface_protocol: name the protocol or handshake style (e.g. "request-grant",
   "ready-valid", "Wishbone", "SPI", "serial", "parallel").
8. granularity: one of "primitive", "leaf", or "composite".
9. If you are genuinely uncertain about a field, use "unknown".
10. Do NOT output fields outside this schema:
    core_function, algorithm, structure, interface_protocol, granularity, keywords.
"""


def _format_input(semantic_input: dict[str, Any]) -> str:
    import json

    lines: list[str] = []
    lines.append(f"Module: {semantic_input.get('module', 'unknown')}")
    lines.append(f"Project: {semantic_input.get('project', 'unknown')}")
    lines.append(f"Candidate kind: {semantic_input.get('candidate_kind', 'standalone')}")

    params = semantic_input.get("parameters", [])
    if params:
        lines.append(f"Parameters: {', '.join(params)}")

    ports = semantic_input.get("ports", [])
    if ports:
        lines.append("Ports:")
        for port in ports:
            lines.append(f"  {port['direction']} {port['name']} (width: {port.get('width', '1')})")

    deps = semantic_input.get("dependencies", [])
    if deps:
        lines.append(f"Dependencies: {', '.join(deps)}")

    used_by = semantic_input.get("used_by", [])
    if used_by:
        lines.append(f"Used by: {', '.join(used_by)}")

    comments = semantic_input.get("comments", [])
    if comments:
        lines.append(f"Comments: {'; '.join(comments[:5])}")

    structural = semantic_input.get("structural_facts", {})
    if structural:
        lines.append("Structural facts:")
        for key, val in structural.items():
            lines.append(f"  {key}: {val}")

    snippets = semantic_input.get("source_snippets", [])
    if snippets:
        lines.append(f"Source snippets: {'; '.join(snippets[:3])}")

    return "\n".join(lines)
