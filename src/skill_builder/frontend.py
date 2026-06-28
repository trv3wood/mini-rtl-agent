from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .instance_extractor import extract_instances_from_pyslang_json
from .models import ModuleIR, ParameterInfo, PortInfo, SourceLocation
from .parser import (
    detect_always_blocks,
    detect_clock_candidates,
    detect_continuous_assignments,
    detect_memory_candidates,
    detect_reset_candidates,
    detect_states,
    extract_comments,
    parse_instances,
    parse_modules_with_regex,
)


LAST_PARSE_WARNINGS: list[str] = []


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _identifier_text(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    if node.get("kind") == "Identifier" and isinstance(node.get("text"), str):
        return node["text"]
    for child in _walk(node):
        if child.get("kind") == "Identifier" and isinstance(child.get("text"), str):
            return child["text"]
    return ""


def _node_text(node: Any) -> str:
    if isinstance(node, dict):
        if isinstance(node.get("text"), str):
            return node["text"]
        return " ".join(part for part in (_node_text(value) for value in node.values()) if part).strip()
    if isinstance(node, list):
        return " ".join(part for part in (_node_text(value) for value in node) if part).strip()
    return ""


def _range_width(data_type: Any) -> str:
    if not isinstance(data_type, dict):
        return "1"
    dimensions = data_type.get("dimensions", [])
    if not isinstance(dimensions, list) or not dimensions:
        return "1"
    selector = dimensions[0].get("specifier", {}).get("selector", {}) if isinstance(dimensions[0], dict) else {}
    left = _node_text(selector.get("left")) if isinstance(selector, dict) else ""
    right = _node_text(selector.get("right")) if isinstance(selector, dict) else ""
    if left and right:
        return f"[{left}:{right}]"
    return "1"


def _parameters_from_header(header: dict[str, Any], source: SourceLocation) -> list[ParameterInfo]:
    parameters = header.get("parameters", {})
    declarations = parameters.get("declarations", []) if isinstance(parameters, dict) else []
    out: list[ParameterInfo] = []
    for declaration in declarations:
        if not isinstance(declaration, dict) or declaration.get("kind") != "ParameterDeclaration":
            continue
        for declarator in declaration.get("declarators", []):
            if not isinstance(declarator, dict):
                continue
            name = _identifier_text(declarator.get("name"))
            if not name:
                continue
            initializer = declarator.get("initializer", {})
            default = _node_text(initializer.get("expr")) if isinstance(initializer, dict) else None
            out.append(ParameterInfo(name=name, default=default or None, kind="parameter", source=source))
    return out


def _ports_from_header(header: dict[str, Any], source: SourceLocation) -> list[PortInfo]:
    ports_node = header.get("ports", {})
    raw_ports = ports_node.get("ports", []) if isinstance(ports_node, dict) else []
    out: list[PortInfo] = []
    for port in raw_ports:
        if not isinstance(port, dict) or not port.get("kind", "").endswith("Port"):
            continue
        header_node = port.get("header", {})
        direction_node = header_node.get("direction", {}) if isinstance(header_node, dict) else {}
        direction = str(direction_node.get("text", "input")) if isinstance(direction_node, dict) else "input"
        data_type = header_node.get("dataType", {}) if isinstance(header_node, dict) else {}
        name = _identifier_text(port.get("declarator", {}).get("name") if isinstance(port.get("declarator"), dict) else {})
        if not name:
            continue
        out.append(
            PortInfo(
                name=name,
                direction=direction,
                width=_range_width(data_type),
                data_type="wire",
                source=source,
            )
        )
    return out


def _module_names_from_pyslang_json(tree_json: str) -> list[str]:
    tree = json.loads(tree_json)
    root = tree.get("root", {}) if isinstance(tree, dict) else {}
    members = root.get("members", []) if isinstance(root, dict) else []
    names: list[str] = []
    for member in members:
        if not isinstance(member, dict) or member.get("kind") != "ModuleDeclaration":
            continue
        header = member.get("header", {})
        name = _identifier_text(header.get("name")) if isinstance(header, dict) else ""
        if name and name not in names:
            names.append(name)
    return names


def _module_headers_from_pyslang_json(tree_json: str) -> dict[str, dict[str, Any]]:
    tree = json.loads(tree_json)
    root = tree.get("root", {}) if isinstance(tree, dict) else {}
    members = root.get("members", []) if isinstance(root, dict) else []
    headers: dict[str, dict[str, Any]] = {}
    for member in members:
        if not isinstance(member, dict) or member.get("kind") != "ModuleDeclaration":
            continue
        header = member.get("header", {})
        name = _identifier_text(header.get("name")) if isinstance(header, dict) else ""
        if name and isinstance(header, dict):
            headers[name] = header
    return headers


def _module_ir_from_pyslang_name(
    name: str,
    path: Path,
    source_text: str,
    instances_by_module: dict[str, list],
    header: dict[str, Any] | None,
) -> ModuleIR:
    source = SourceLocation(str(path), 1, source_text.count("\n") + 1)
    header = header or {}
    ports = _ports_from_header(header, source)
    return ModuleIR(
        name=name,
        source_file=str(path),
        ports=ports,
        parameters=_parameters_from_header(header, source),
        instances=instances_by_module.get(name, []),
        clock_candidates=detect_clock_candidates(ports),
        reset_candidates=detect_reset_candidates(ports),
        memory_candidates=detect_memory_candidates(source_text, source_text, path, 0),
        always_blocks=detect_always_blocks(source_text, source_text, path, 0),
        continuous_assignments=detect_continuous_assignments(source_text, source_text, path, 0),
        assertions=[],
        parse_backend="pyslang",
        syntax_backend="pyslang",
        instance_backend="pyslang_ast",
        parameter_backend="pyslang_ast",
        port_backend="pyslang_ast",
        semantic_status="syntax_only",
        parse_warnings=[
            "pyslang extracted module declaration and ANSI header metadata"
        ],
        comments=extract_comments(source_text),
        states=detect_states(source_text),
        source_text=source_text,
    )


def _parse_with_pyslang(path: Path, include_dirs: list[Path], defines: dict[str, str]) -> list[ModuleIR]:
    try:
        import pyslang  # type: ignore[import-not-found]
    except Exception as exc:
        raise RuntimeError(f"pyslang unavailable: {exc}") from exc

    try:
        syntax_tree = pyslang.syntax.SyntaxTree.fromFile(str(path))
        diagnostics = getattr(syntax_tree, "diagnostics", [])
        diagnostics = list(diagnostics or [])
        if diagnostics:
            detail = "; ".join(str(diagnostic) for diagnostic in diagnostics[:5])
            raise RuntimeError(f"pyslang diagnostics: {detail}")
    except Exception as exc:
        raise RuntimeError(f"pyslang failed for {path}: {exc}") from exc

    source_text = path.read_text(encoding="utf-8", errors="ignore")
    tree_json = syntax_tree.to_json()
    module_names = _module_names_from_pyslang_json(tree_json)
    module_headers = _module_headers_from_pyslang_json(tree_json)
    instances_by_module = extract_instances_from_pyslang_json(tree_json, path, source_text)
    regex_modules = {module.name: module for module in parse_modules_with_regex(path)}
    modules: list[ModuleIR] = []
    for name in module_names:
        module = regex_modules.get(name)
        used_regex_metadata = module is not None
        if module is None:
            module = _module_ir_from_pyslang_name(name, path, source_text, instances_by_module, module_headers.get(name))
        else:
            module.instances = instances_by_module.get(module.name, module.instances)
        module.parse_backend = "pyslang"
        module.syntax_backend = "pyslang"
        module.instance_backend = "pyslang_ast"
        if used_regex_metadata:
            module.parameter_backend = "regex" if module.parameters else module.parameter_backend
            module.port_backend = "regex" if module.ports else module.port_backend
        module.semantic_status = "syntax_only"
        module.parse_warnings.append(
            "pyslang accepted syntax; frontend metadata extracted deterministically"
        )
        modules.append(module)
    return modules


def _merge_modules(modules: list[ModuleIR]) -> list[ModuleIR]:
    merged: list[ModuleIR] = []
    seen: set[tuple[str, str]] = set()
    for module in modules:
        key = (module.name, module.source_file)
        if key in seen:
            module.parse_warnings.append(f"duplicate module ignored: {module.name} in {module.source_file}")
            continue
        seen.add(key)
        merged.append(module)
    return merged


def parse_project(
    rtl_files: list[Path],
    include_dirs: list[Path] | None = None,
    defines: dict[str, str] | None = None,
) -> list[ModuleIR]:
    global LAST_PARSE_WARNINGS
    include_dirs = include_dirs or []
    defines = defines or {}
    modules: list[ModuleIR] = []
    all_warnings: list[str] = []

    for rtl_file in rtl_files:
        file_warnings: list[str] = []
        try:
            parsed = _parse_with_pyslang(rtl_file, include_dirs, defines)
            modules.extend(parsed)
            continue
        except Exception as exc:
            file_warnings.append(f"{rtl_file}: {exc}; falling back to regex parser")

        try:
            parsed = parse_modules_with_regex(rtl_file)
        except Exception as exc:
            file_warnings.append(f"{rtl_file}: regex parser failed: {exc}")
            all_warnings.extend(file_warnings)
            continue

        if not parsed:
            file_warnings.append(f"{rtl_file}: regex parser found no modules")
        for module in parsed:
            module.parse_warnings.extend(file_warnings)
        modules.extend(parsed)
        all_warnings.extend(file_warnings)

    LAST_PARSE_WARNINGS = all_warnings
    return _merge_modules(modules)


def get_last_parse_warnings() -> list[str]:
    return list(LAST_PARSE_WARNINGS)
