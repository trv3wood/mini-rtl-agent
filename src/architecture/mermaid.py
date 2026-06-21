from __future__ import annotations

import re


def node_id(name: str) -> str:
    value = re.sub(r"[^0-9a-zA-Z_]", "_", name.strip())
    if not value:
        return "Node"
    if value[0].isdigit():
        return f"N_{value}"
    return value


def generate_mermaid(architecture: dict) -> str:
    lines = ["graph TD"]
    for submodule in architecture.get("submodules", []):
        name = str(submodule["name"])
        lines.append(f"  {node_id(name)}[{name}]")
    for connection in architecture.get("connections", []):
        source = node_id(str(connection["from"]))
        target = node_id(str(connection["to"]))
        label = str(connection.get("signal", connection.get("purpose", ""))).strip()
        if label:
            lines.append(f"  {source} -- {label} --> {target}")
        else:
            lines.append(f"  {source} --> {target}")
    return "\n".join(lines) + "\n"
