from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_engineer_spec_prompt(
    *,
    final_ip_context: dict[str, Any],
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You generate engineer_spec.v1 JSON for the final generated IP, not the original skill. "
                "Use final_ip_context as terminal truth for module name, ports, parameters, and syntax status. "
                "Return valid JSON only. Do not include Markdown. Do not include evidence, provenance, tool_runs, "
                "SystemVerilog, UVM, or source code. Do not invent missing semantics; put uncertainty in "
                "assumptions_and_constraints.unknowns. Keep the JSON concise: each prose string should be short, "
                "arrays should usually contain 1-3 items, and avoid repeating the same fact in multiple fields."
            ),
        },
        {
            "role": "user",
            "content": (
                "Generate engineer_spec.v1 with exactly this JSON shape. Replace placeholder strings/lists "
                "with concise values for the final generated IP:\n"
                f"{json.dumps(_engineer_spec_skeleton(), separators=(',', ':'))}\n\n"
                f"final_ip_context:\n{json.dumps(final_ip_context, separators=(',', ':'))}"
            ),
        },
    ]


def generate_engineer_spec(
    *,
    llm_client: Any,
    final_ip_context: dict[str, Any],
    max_repair_attempts: int = 1,
) -> dict[str, Any]:
    messages = build_engineer_spec_prompt(final_ip_context=final_ip_context)
    last_error = ""
    for attempt in range(max_repair_attempts + 1):
        text = llm_client.complete_text(messages, temperature=0.0)
        try:
            spec = _parse_json(text)
            validate_engineer_spec(spec)
            return spec
        except ValueError as exc:
            last_error = str(exc)
            if attempt == max_repair_attempts:
                break
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Repair engineer_spec.v1 JSON. Return valid JSON only, no Markdown. "
                        "Keep it about the final generated IP and mark unknowns explicitly."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Validation error:\n{last_error}\n\nInvalid JSON/content:\n{text}",
                },
            ]
    raise ValueError(f"LLM failed to produce valid engineer_spec.v1: {last_error}")


def validate_engineer_spec(spec: dict[str, Any]) -> None:
    _require(spec, [
        "schema_version",
        "ip_name",
        "source_skill",
        "title",
        "summary",
        "classification",
        "interface",
        "behavior",
        "usage",
        "assumptions_and_constraints",
        "verification_notes",
        "human_review",
    ])
    if spec["schema_version"] != "engineer_spec.v1":
        raise ValueError("engineer_spec.schema_version must be engineer_spec.v1")
    _require(spec["summary"], ["one_sentence", "detailed_description", "design_intent"])
    _require(spec["classification"], ["domain", "category", "granularity", "implementation_style", "statefulness", "clocking_model"])
    _require(spec["interface"], ["ports", "parameters", "clock", "reset", "interface_summary"])
    _require(spec["behavior"], ["functional_behavior", "semantic_rules", "invalid_or_dont_care_behavior", "latency", "throughput"])
    _require(spec["assumptions_and_constraints"], ["assumptions", "constraints", "unknowns"])
    _require(spec["verification_notes"], ["recommended_strategy", "directed_tests", "random_tests", "properties_to_check", "uvm_suitability", "uvm_note"])
    _require(spec["human_review"], ["confidence", "review_focus"])
    if not isinstance(spec["interface"]["ports"], list):
        raise ValueError("engineer_spec.interface.ports must be a list")
    for port in spec["interface"]["ports"]:
        _require(port, ["name", "direction", "width", "role", "description"])


def write_engineer_spec(
    spec: dict[str, Any],
    output_path: Path,
) -> Path:
    validate_engineer_spec(spec)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def _parse_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def _require(mapping: dict[str, Any], keys: list[str]) -> None:
    missing = [key for key in keys if key not in mapping]
    if missing:
        raise ValueError(f"missing required key(s): {', '.join(missing)}")


def _engineer_spec_skeleton() -> dict[str, Any]:
    return {
        "schema_version": "engineer_spec.v1",
        "ip_name": "string",
        "source_skill": "string",
        "title": "string",
        "summary": {
            "one_sentence": "string",
            "detailed_description": "string",
            "design_intent": "string",
        },
        "classification": {
            "domain": "string",
            "category": "string",
            "granularity": "leaf | wrapper_ip | composite_ip | unknown",
            "implementation_style": "combinational_logic | sequential_logic | protocol_logic | mixed | unknown",
            "statefulness": "stateless | stateful | unknown",
            "clocking_model": "no_clock | single_clock | multi_clock | unknown",
        },
        "interface": {
            "ports": [
                {
                    "name": "string",
                    "direction": "input | output | inout",
                    "width": "integer | string",
                    "role": "string",
                    "description": "string",
                }
            ],
            "parameters": [{"name": "string", "value": "string | integer | null", "description": "string"}],
            "clock": {"name": "string", "description": "string"},
            "reset": {
                "name": "string",
                "polarity": "active_high | active_low | unknown",
                "synchronous": "true | false | unknown",
                "description": "string",
            },
            "interface_summary": "string",
        },
        "behavior": {
            "functional_behavior": ["string"],
            "semantic_rules": ["string"],
            "invalid_or_dont_care_behavior": ["string"],
            "latency": {"type": "combinational | fixed_cycle | variable | unknown", "cycles": "integer | null", "note": "string"},
            "throughput": {"type": "combinational | one_per_cycle | protocol_limited | unknown", "note": "string"},
        },
        "usage": {
            "typical_use_cases": ["string"],
            "not_suitable_for": ["string"],
            "integration_notes": ["string"],
        },
        "assumptions_and_constraints": {
            "assumptions": ["string"],
            "constraints": ["string"],
            "unknowns": ["string"],
        },
        "verification_notes": {
            "recommended_strategy": "string",
            "directed_tests": ["string"],
            "random_tests": ["string"],
            "properties_to_check": ["string"],
            "uvm_suitability": "low | medium | high | unknown",
            "uvm_note": "string",
        },
        "human_review": {"confidence": "low | medium | high", "review_focus": ["string"]},
    }
