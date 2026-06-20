from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "data" / "rtl_skills"
INDEX_PATH = SKILL_DIR / "index.json"

REQUIRED_TOP_FIELDS = {
    "name",
    "skill_type",
    "description",
    "ports",
    "constraints",
    "dependencies",
    "implementation_notes",
    "source_refs",
    "verification_goals",
    "keywords",
}
REQUIRED_PORT_FIELDS = {"name", "direction", "width", "description"}
REQUIRED_SOURCE_REF_FIELDS = {"project", "repository", "commit", "path", "module", "url", "license"}
VALID_DIRECTIONS = {"input", "output", "inout"}
VALID_SKILL_TYPES = {"module", "primitive"}


def load_module_info(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level JSON must be an object")
    return data


def validate_module(data: dict[str, Any], path: Path) -> list[str]:
    errors: list[str] = []
    missing = REQUIRED_TOP_FIELDS - data.keys()
    if missing:
        errors.append(f"{path}: missing fields: {', '.join(sorted(missing))}")

    name = data.get("name")
    if not isinstance(name, str) or not name:
        errors.append(f"{path}: name must be a non-empty string")
    elif path.parent.name != name:
        errors.append(f"{path}: parent directory must match name '{name}'")

    skill_type = data.get("skill_type")
    if skill_type not in VALID_SKILL_TYPES:
        errors.append(f"{path}: skill_type must be one of {sorted(VALID_SKILL_TYPES)}")
    elif skill_type == "module":
        if not isinstance(data.get("states"), list) or not data.get("states"):
            errors.append(f"{path}: module skills must define a non-empty states list")
        if "behavior" in data:
            errors.append(f"{path}: module skills should use states instead of behavior")
    elif skill_type == "primitive":
        if not isinstance(data.get("behavior"), list) or not data.get("behavior"):
            errors.append(f"{path}: primitive skills must define a non-empty behavior list")
        if "states" in data:
            errors.append(f"{path}: primitive skills should use behavior instead of states")

    ports = data.get("ports")
    if not isinstance(ports, list) or not ports:
        errors.append(f"{path}: ports must be a non-empty list")
    else:
        seen_ports: set[str] = set()
        for idx, port in enumerate(ports):
            if not isinstance(port, dict):
                errors.append(f"{path}: ports[{idx}] must be an object")
                continue
            missing_port = REQUIRED_PORT_FIELDS - port.keys()
            if missing_port:
                errors.append(
                    f"{path}: ports[{idx}] missing fields: {', '.join(sorted(missing_port))}"
                )
            port_name = port.get("name")
            if not isinstance(port_name, str) or not port_name:
                errors.append(f"{path}: ports[{idx}].name must be a non-empty string")
            elif port_name in seen_ports:
                errors.append(f"{path}: duplicate port '{port_name}'")
            else:
                seen_ports.add(port_name)
            direction = port.get("direction")
            if direction not in VALID_DIRECTIONS:
                errors.append(f"{path}: port '{port_name}' has invalid direction '{direction}'")

    for list_field in (
        "constraints",
        "implementation_notes",
        "source_refs",
        "verification_goals",
        "keywords",
    ):
        value = data.get(list_field)
        if not isinstance(value, list) or not value:
            errors.append(f"{path}: {list_field} must be a non-empty list")

    source_refs = data.get("source_refs")
    if isinstance(source_refs, list):
        for idx, source_ref in enumerate(source_refs):
            if not isinstance(source_ref, dict):
                errors.append(f"{path}: source_refs[{idx}] must be an object")
                continue
            missing_source_fields = REQUIRED_SOURCE_REF_FIELDS - source_ref.keys()
            if missing_source_fields:
                errors.append(
                    f"{path}: source_refs[{idx}] missing fields: "
                    f"{', '.join(sorted(missing_source_fields))}"
                )
            if not source_ref.get("path"):
                errors.append(f"{path}: source_refs[{idx}].path must be non-empty")
            if not source_ref.get("url"):
                errors.append(f"{path}: source_refs[{idx}].url must be non-empty")

    dependencies = data.get("dependencies")
    if not isinstance(dependencies, list):
        errors.append(f"{path}: dependencies must be a list")

    return errors


def build_index() -> tuple[list[dict[str, Any]], list[str]]:
    module_paths = sorted(SKILL_DIR.glob("*/module_info.json"))
    modules = [load_module_info(path) for path in module_paths]
    errors: list[str] = []
    for path, module in zip(module_paths, modules):
        errors.extend(validate_module(module, path))

    known_names = {module.get("name") for module in modules if isinstance(module.get("name"), str)}
    index = []
    for module in sorted(modules, key=lambda item: item["name"]):
        unresolved = [dep for dep in module["dependencies"] if dep not in known_names]
        index.append(
            {
                "name": module["name"],
                "skill_type": module["skill_type"],
                "category": module.get("category", ""),
                "description": module["description"],
                "interfaces": module.get("interfaces", []),
                "dependencies": module["dependencies"],
                "unresolved_dependencies": unresolved,
                "source_ref_count": len(module["source_refs"]),
                "has_constraints": bool(module["constraints"]),
                "has_implementation_notes": bool(module["implementation_notes"]),
                "has_verification_goals": bool(module["verification_goals"]),
                "keywords": module["keywords"],
                "path": str(
                    (SKILL_DIR / module["name"] / "module_info.json").relative_to(ROOT)
                ),
            }
        )
    return index, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate RTL skill metadata and build an index.")
    parser.add_argument("--check", action="store_true", help="Validate only; do not write index.json.")
    args = parser.parse_args()

    if not SKILL_DIR.exists():
        print(f"missing skill directory: {SKILL_DIR}")
        return 1

    index, errors = build_index()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    if not args.check:
        INDEX_PATH.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {INDEX_PATH.relative_to(ROOT)} ({len(index)} skills)")
    else:
        print(f"validated {len(index)} skills")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
