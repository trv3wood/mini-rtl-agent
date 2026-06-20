from __future__ import annotations

from typing import Any


REQUIRED_TOP_FIELDS = {
    "name",
    "skill_type",
    "category",
    "description",
    "source_refs",
    "parameters",
    "ports",
    "constraints",
    "dependencies",
    "interfaces",
    "patterns",
    "implementation_notes",
    "test_strategy",
    "verification_goals",
    "keywords",
    "provenance",
}
REQUIRED_PORT_FIELDS = {"name", "direction", "width", "description"}
REQUIRED_PROVENANCE_FIELDS = {
    "source_file",
    "detected_module_name",
    "builder_version",
    "parser_mode",
}
VALID_DIRECTIONS = {"input", "output", "inout"}


def validate_module_info(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = REQUIRED_TOP_FIELDS - data.keys()
    if missing:
        errors.append(f"missing top-level fields: {', '.join(sorted(missing))}")

    if data.get("skill_type") != "module":
        errors.append("skill_type must be 'module'")

    ports = data.get("ports")
    if not isinstance(ports, list):
        errors.append("ports must be a list")
    else:
        seen_ports: set[str] = set()
        for idx, port in enumerate(ports):
            if not isinstance(port, dict):
                errors.append(f"ports[{idx}] must be an object")
                continue
            missing_port_fields = REQUIRED_PORT_FIELDS - port.keys()
            if missing_port_fields:
                errors.append(
                    f"ports[{idx}] missing fields: {', '.join(sorted(missing_port_fields))}"
                )
            name = port.get("name")
            if not isinstance(name, str) or not name:
                errors.append(f"ports[{idx}].name must be a non-empty string")
            elif name in seen_ports:
                errors.append(f"duplicate port: {name}")
            else:
                seen_ports.add(name)
            if port.get("direction") not in VALID_DIRECTIONS:
                errors.append(f"ports[{idx}].direction must be one of {sorted(VALID_DIRECTIONS)}")

    for field in (
        "source_refs",
        "parameters",
        "constraints",
        "dependencies",
        "interfaces",
        "patterns",
        "implementation_notes",
        "test_strategy",
        "verification_goals",
        "keywords",
    ):
        if field in data and not isinstance(data[field], list):
            errors.append(f"{field} must be a list")

    provenance = data.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("provenance must be an object")
    else:
        missing_provenance = REQUIRED_PROVENANCE_FIELDS - provenance.keys()
        if missing_provenance:
            errors.append(
                f"provenance missing fields: {', '.join(sorted(missing_provenance))}"
            )
        if provenance.get("parser_mode") != "deterministic":
            errors.append("provenance.parser_mode must be 'deterministic'")
        if provenance.get("source_file") is None:
            errors.append("provenance.source_file must be set")
        if provenance.get("detected_module_name") != data.get("name"):
            errors.append("provenance.detected_module_name must match name")

    return errors


def require_valid_module_info(data: dict[str, Any]) -> None:
    errors = validate_module_info(data)
    if errors:
        raise ValueError("; ".join(errors))
