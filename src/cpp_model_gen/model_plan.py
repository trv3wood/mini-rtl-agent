from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_cpp_model_prompt(
    *,
    final_ip_context: dict[str, Any],
    engineer_spec: dict[str, Any],
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You generate cpp_model.v1 JSON for a C++17 reference model. "
                "Use final_ip_context as terminal truth for module name, ports, parameters, and syntax status. "
                "Use engineer_spec as the behavior contract. Return valid JSON only. Do not write C++ code. "
                "Do not invent missing semantics; represent missing or conflicting semantics as unknowns/conflicts. "
                "If semantics are blocking, set model_kind='unsupported' or add a blocking conflict."
            ),
        },
        {
            "role": "user",
            "content": (
                "Generate cpp_model.v1 with exactly this JSON shape. Replace placeholder strings/lists "
                "with values for the final generated IP. Do not include C++ code here:\n"
                f"{json.dumps(_cpp_model_skeleton(), indent=2)}\n\n"
                f"final_ip_context:\n{json.dumps(final_ip_context, indent=2)}\n\n"
                f"engineer_spec:\n{json.dumps(engineer_spec, indent=2)}"
            ),
        },
    ]


def generate_cpp_model_plan(
    *,
    llm_client: Any,
    final_ip_context: dict[str, Any],
    engineer_spec: dict[str, Any],
    max_repair_attempts: int = 1,
) -> dict[str, Any]:
    messages = build_cpp_model_prompt(final_ip_context=final_ip_context, engineer_spec=engineer_spec)
    last_error = ""
    for attempt in range(max_repair_attempts + 1):
        text = llm_client.complete_text(messages, temperature=0.0)
        try:
            plan = _parse_json(text)
            validate_cpp_model_plan(plan)
            return plan
        except ValueError as exc:
            last_error = str(exc)
            if attempt == max_repair_attempts:
                break
            messages = [
                {
                    "role": "system",
                    "content": "Repair cpp_model.v1 JSON. Return valid JSON only. Do not write C++ code.",
                },
                {"role": "user", "content": f"Validation error:\n{last_error}\n\nInvalid JSON/content:\n{text}"},
            ]
    raise ValueError(f"LLM failed to produce valid cpp_model.v1: {last_error}")


def validate_cpp_model_plan(plan: dict[str, Any]) -> None:
    _require(plan, [
        "schema_version",
        "ip_name",
        "source_skill",
        "model_name",
        "model_role",
        "model_kind",
        "language",
        "equivalence_scope",
        "types",
        "function_signature",
        "behavior_contract",
        "test_vectors",
        "generation_outputs",
    ])
    if plan["schema_version"] != "cpp_model.v1":
        raise ValueError("cpp_model.schema_version must be cpp_model.v1")
    if plan["language"] != "cpp17":
        raise ValueError("cpp_model.language must be cpp17")
    _require(plan["equivalence_scope"], ["visible_outputs_only", "cycle_accurate", "four_state_logic", "timing_delays", "notes"])
    _require(plan["function_signature"], ["name", "return_type", "arguments"])
    _require(plan["behavior_contract"], ["preconditions", "postconditions", "semantic_choices", "dont_care_conditions", "unknowns", "conflicts"])
    _require(plan["generation_outputs"], ["header", "source", "test", "build"])
    if not isinstance(plan["function_signature"]["arguments"], list):
        raise ValueError("cpp_model.function_signature.arguments must be a list")
    if not isinstance(plan["test_vectors"], list):
        raise ValueError("cpp_model.test_vectors must be a list")
    for vector in plan["test_vectors"]:
        _require(vector, ["name", "inputs", "expected", "check_mask"])


def has_blocking_cpp_model_issue(plan: dict[str, Any]) -> bool:
    try:
        validate_cpp_model_plan(plan)
    except ValueError:
        return True
    if plan.get("model_kind") == "unsupported":
        return True
    conflicts = plan.get("behavior_contract", {}).get("conflicts", [])
    if any(bool(item.get("blocking")) for item in conflicts if isinstance(item, dict)):
        return True
    signature = plan.get("function_signature", {})
    return not signature.get("name") or not signature.get("return_type") or not plan.get("test_vectors")


def write_cpp_model_plan(
    plan: dict[str, Any],
    output_path: Path,
) -> Path:
    validate_cpp_model_plan(plan)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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


def _cpp_model_skeleton() -> dict[str, Any]:
    return {
        "schema_version": "cpp_model.v1",
        "ip_name": "string",
        "source_skill": "string",
        "model_name": "string",
        "model_role": "golden_reference_model",
        "model_kind": "combinational_function | stateful_step_model | protocol_helper_model | unsupported",
        "language": "cpp17",
        "equivalence_scope": {
            "visible_outputs_only": True,
            "cycle_accurate": False,
            "four_state_logic": False,
            "timing_delays": False,
            "notes": ["string"],
        },
        "types": [
            {
                "name": "string",
                "fields": [{"name": "string", "type": "string", "width": "integer | null", "semantic": "string"}],
            }
        ],
        "function_signature": {
            "name": "string",
            "return_type": "string",
            "arguments": [{"name": "string", "type": "string", "width": "integer | null", "role": "string"}],
        },
        "behavior_contract": {
            "preconditions": ["string"],
            "postconditions": ["string"],
            "semantic_choices": ["string"],
            "dont_care_conditions": ["string"],
            "unknowns": ["string"],
            "conflicts": [{"topic": "string", "description": "string", "blocking": True}],
        },
        "test_vectors": [
            {
                "name": "string",
                "inputs": {"key": "value"},
                "expected": {"key": "value"},
                "check_mask": {"key": "compare | ignore"},
            }
        ],
        "generation_outputs": {
            "header": "string",
            "source": "string",
            "test": "string",
            "build": "string",
        },
    }
