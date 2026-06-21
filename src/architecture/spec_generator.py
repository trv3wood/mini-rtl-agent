from __future__ import annotations

import re
from pathlib import Path


def slug(name: str) -> str:
    value = re.sub(r"[^0-9a-zA-Z]+", "_", name.strip()).strip("_").lower()
    return value or "module"


def generate_module_spec(submodule: dict) -> str:
    lines = [
        f"# {submodule['name']}",
        "",
        "## Purpose",
        str(submodule.get("purpose", "")),
        "",
        "## Inputs",
    ]
    lines.extend(f"- `{item}`" for item in submodule.get("inputs", []))
    lines.extend(["", "## Outputs"])
    lines.extend(f"- `{item}`" for item in submodule.get("outputs", []))
    lines.extend(["", "## Constraints"])
    lines.extend(f"- {item}" for item in submodule.get("constraints", []))
    lines.extend(["", "## Dependencies"])
    dependencies = submodule.get("dependencies", [])
    lines.extend(f"- `{item}`" for item in dependencies) if dependencies else lines.append("- None")
    lines.extend(["", "## Likely RTL Patterns"])
    lines.extend(f"- {item}" for item in submodule.get("patterns", []))
    lines.extend(["", "## Skill Mapping", f"- `{submodule.get('skill_category', 'custom')}`", ""])
    return "\n".join(lines)


def write_module_specs(architecture: dict, output_dir: Path) -> list[Path]:
    specs_dir = output_dir / "specs"
    specs_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for submodule in architecture.get("submodules", []):
        path = specs_dir / f"{slug(str(submodule['name']))}.md"
        path.write_text(generate_module_spec(submodule), encoding="utf-8")
        paths.append(path)
    return paths


def generate_architecture_markdown(requirement: str, architecture: dict) -> str:
    lines = [
        f"# {architecture['top_module']} Architecture",
        "",
        "## Requirement",
        requirement,
        "",
        "## Submodules",
    ]
    for submodule in architecture.get("submodules", []):
        lines.extend(
            [
                f"### {submodule['name']}",
                f"- Purpose: {submodule.get('purpose', '')}",
                f"- Skill mapping: `{submodule.get('skill_category', 'custom')}`",
                f"- Dependencies: {', '.join(submodule.get('dependencies', [])) or 'None'}",
                f"- Patterns: {', '.join(submodule.get('patterns', [])) or 'None'}",
                "",
            ]
        )
    lines.append("## Connections")
    for connection in architecture.get("connections", []):
        signal = connection.get("signal", connection.get("purpose", ""))
        lines.append(f"- `{connection['from']}` -> `{connection['to']}`: {signal}")
    lines.extend(["", "## Notes"])
    lines.extend(f"- {note}" for note in architecture.get("notes", []))
    lines.append("")
    return "\n".join(lines)
