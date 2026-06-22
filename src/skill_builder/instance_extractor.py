from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import InstanceInfo, SourceLocation


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _text(node: Any) -> str:
    if isinstance(node, dict):
        if isinstance(node.get("text"), str):
            return node["text"]
        parts = [_text(value) for value in node.values()]
        return " ".join(part for part in parts if part).strip()
    if isinstance(node, list):
        parts = [_text(value) for value in node]
        return " ".join(part for part in parts if part).strip()
    return ""


def _identifier_text(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    if node.get("kind") == "Identifier" and isinstance(node.get("text"), str):
        return node["text"]
    for child in _walk(node):
        if child.get("kind") == "Identifier" and isinstance(child.get("text"), str):
            return child["text"]
    return ""


def _source_location(text: str, path: Path, needle: str, start_at: int) -> tuple[SourceLocation, int]:
    start = text.find(needle, start_at)
    if start < 0:
        start = text.find(needle)
    if start < 0:
        return SourceLocation(str(path)), start_at
    semi = text.find(";", start)
    end = semi + 1 if semi >= 0 else start + len(needle)
    return (
        SourceLocation(
            str(path),
            text.count("\n", 0, start) + 1,
            text.count("\n", 0, end) + 1,
        ),
        end,
    )


def _named_assignments(nodes: list[dict[str, Any]], name_key: str = "name") -> dict[str, str]:
    assignments: dict[str, str] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        name = _identifier_text(node.get(name_key))
        if not name:
            continue
        expr = _text(node.get("expr", ""))
        assignments[name] = expr
    return assignments


def _port_connections(instance: dict[str, Any]) -> dict[str, str]:
    connections = instance.get("connections", [])
    if not isinstance(connections, list):
        return {}
    return _named_assignments([conn for conn in connections if isinstance(conn, dict)])


def _parameter_overrides(instantiation: dict[str, Any]) -> dict[str, str]:
    parameters = instantiation.get("parameters", {})
    if not isinstance(parameters, dict):
        return {}
    assignments = parameters.get("parameters", [])
    if not isinstance(assignments, list):
        return {}
    return _named_assignments([param for param in assignments if isinstance(param, dict)])


def _module_declarations(tree: dict[str, Any]) -> dict[str, dict[str, Any]]:
    modules: dict[str, dict[str, Any]] = {}
    root = tree.get("root", {})
    members = root.get("members", []) if isinstance(root, dict) else []
    for member in members:
        if not isinstance(member, dict) or member.get("kind") != "ModuleDeclaration":
            continue
        header = member.get("header", {})
        name = _identifier_text(header.get("name")) if isinstance(header, dict) else ""
        if name:
            modules[name] = member
    return modules


def extract_instances_from_pyslang_json(tree_json: str, source_path: Path, source_text: str) -> dict[str, list[InstanceInfo]]:
    tree = json.loads(tree_json)
    modules = _module_declarations(tree)
    instances_by_module: dict[str, list[InstanceInfo]] = {name: [] for name in modules}
    cursor_by_module = {name: 0 for name in modules}
    for module_name, module_node in modules.items():
        for node in _walk(module_node.get("members", [])):
            if node.get("kind") != "HierarchyInstantiation":
                continue
            instantiated_module = _identifier_text(node.get("type"))
            if not instantiated_module:
                continue
            parameter_overrides = _parameter_overrides(node)
            raw_instances = node.get("instances", [])
            if not isinstance(raw_instances, list):
                continue
            for raw_instance in raw_instances:
                if not isinstance(raw_instance, dict):
                    continue
                decl = raw_instance.get("decl", {})
                instance_name = _identifier_text(decl.get("name") if isinstance(decl, dict) else decl)
                if not instance_name:
                    continue
                source, next_cursor = _source_location(source_text, source_path, instance_name, cursor_by_module[module_name])
                cursor_by_module[module_name] = next_cursor
                instances_by_module[module_name].append(
                    InstanceInfo(
                        module_name=instantiated_module,
                        instance_name=instance_name,
                        parameter_overrides=parameter_overrides,
                        port_connections=_port_connections(raw_instance),
                        source=source,
                    )
                )
    return instances_by_module
