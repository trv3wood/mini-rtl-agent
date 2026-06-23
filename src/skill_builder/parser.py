from __future__ import annotations

import re
from pathlib import Path

from .models import (
    InstanceInfo,
    ModuleIR,
    ModuleInfo,
    Parameter,
    ParameterInfo,
    Port,
    PortInfo,
    SourceLocation,
    StructuralFact,
)


MODULE_RE = re.compile(
    r"\bmodule\s+([a-zA-Z_][a-zA-Z0-9_$]*)\s*(?:#\s*\((?P<params>.*?)\))?\s*\((?P<ports>.*?)\)\s*;",
    re.S,
)
COMMENT_RE = re.compile(r"//(?P<line>.*?$)|/\*(?P<block>.*?)\*/", re.S | re.M)
DECL_RE = re.compile(
    r"\b(input|output|inout)\b\s*(?:(wire|reg|logic)\b\s*)?(?P<width>\[[^\]]+\])?\s*(?P<names>[^;]+);",
    re.S,
)
STATE_NAME_RE = re.compile(r"\b(?:localparam|parameter)\b[^;=]*?\b([A-Z][A-Z0-9_]{2,})\b\s*=", re.S)
MEMORY_DECL_RE = re.compile(
    r"\b(?P<kind>reg|logic)\b\s*"
    r"(?P<packed>(?:\[[^\]]+\]\s*)*)"
    r"(?P<name>[a-zA-Z_][a-zA-Z0-9_$]*)\s*"
    r"(?P<unpacked>(?:\[[^\]]+\]\s*)+)\s*;",
    re.S,
)
ALWAYS_RE = re.compile(r"\balways(?:_[a-zA-Z0-9_]+)?\b\s*(?:@\s*\((?P<sensitivity>.*?)\))?", re.S)
ASSIGN_RE = re.compile(r"\bassign\s+(?P<lhs>[^=;]+?)\s*=\s*(?P<rhs>.*?);", re.S)
ASSERTION_RE = re.compile(
    r"\b(?P<kind>assert|assume|cover)\b\s*(?:property\s*)?\((?P<expr>.*?)\)\s*;",
    re.S,
)
INSTANCE_RE = re.compile(
    r"\b(?P<module>[a-zA-Z_][a-zA-Z0-9_$]*)\s*"
    r"(?:#\s*\((?P<params>.*?)\)\s*)?"
    r"(?P<instance>[a-zA-Z_][a-zA-Z0-9_$]*)\s*"
    r"\((?P<ports>.*?)\)\s*;",
    re.S,
)
INSTANCE_KEYWORDS = {
    "always",
    "assign",
    "case",
    "else",
    "for",
    "forever",
    "function",
    "generate",
    "if",
    "initial",
    "module",
    "task",
    "while",
}


def strip_comments(text: str) -> str:
    return COMMENT_RE.sub("", text)


def extract_comments(text: str, limit: int = 12) -> list[str]:
    comments: list[str] = []
    for match in COMMENT_RE.finditer(text):
        raw = match.group("line") if match.group("line") is not None else match.group("block")
        if raw is None:
            continue
        cleaned = " ".join(line.strip(" /*\t") for line in raw.splitlines()).strip()
        if cleaned:
            comments.append(cleaned)
        if len(comments) >= limit:
            break
    return comments


def split_top_level(text: str) -> list[str]:
    items: list[str] = []
    start = 0
    depth = 0
    for idx, ch in enumerate(text):
        if ch in "([":
            depth += 1
        elif ch in ")]" and depth > 0:
            depth -= 1
        elif ch == "," and depth == 0:
            items.append(text[start:idx].strip())
            start = idx + 1
    tail = text[start:].strip()
    if tail:
        items.append(tail)
    return items


def parse_width(width: str | None) -> str:
    if not width:
        return "1"
    return " ".join(width.strip().split())


def clean_name(name: str) -> str:
    name = name.strip()
    name = name.split("=")[0].strip()
    name = re.sub(r"\[[^\]]+\]", "", name).strip()
    return name


def is_identifier(name: str) -> bool:
    return bool(re.match(r"^[a-zA-Z_][a-zA-Z0-9_$]*$", name))


def parse_parameters(param_text: str | None) -> list[Parameter]:
    if not param_text:
        return []
    params: list[Parameter] = []
    for item in split_top_level(strip_comments(param_text)):
        item = item.strip()
        item = re.sub(r"^(parameter|localparam)\s+", "", item).strip()
        item = re.sub(r"^(integer|int|logic|reg|wire)\s+", "", item).strip()
        width_match = re.match(r"^\[[^\]]+\]\s+", item)
        if width_match:
            item = item[width_match.end() :].strip()
        if not item:
            continue
        if "=" in item:
            name, default = item.split("=", 1)
            params.append(Parameter(clean_name(name), default.strip(), ""))
        else:
            params.append(Parameter(clean_name(item), "", ""))
    return [param for param in params if is_identifier(param.name)]


def parse_parameter_infos(param_text: str | None, source: SourceLocation) -> list[ParameterInfo]:
    return [
        ParameterInfo(param.name, param.default or None, "parameter", source)
        for param in parse_parameters(param_text)
    ]


def parse_ansi_ports(port_text: str) -> list[Port]:
    ports: list[Port] = []
    last_direction = ""
    last_type = "wire"
    last_width = "1"
    for item in split_top_level(strip_comments(port_text)):
        item = " ".join(item.replace("\n", " ").split())
        if not item:
            continue
        match = re.match(
            r"^(input|output|inout)\b\s*(?:(wire|reg|logic)\b\s*)?(\[[^\]]+\]\s*)?(.*)$",
            item,
        )
        if match:
            last_direction = match.group(1)
            last_type = match.group(2) or ("reg" if last_direction == "output" else "wire")
            last_width = parse_width(match.group(3))
            names = match.group(4)
        else:
            if not last_direction:
                ports.append(Port(clean_name(item), "input", "1", "wire", ""))
                continue
            names = item
        for name_part in split_top_level(names):
            name = clean_name(name_part)
            if is_identifier(name):
                ports.append(
                    Port(
                        name=name,
                        direction=last_direction,
                        width=last_width,
                        data_type=last_type,
                        description="",
                    )
                )
    return ports


def parse_body_ports(body: str, header_ports: list[Port]) -> list[Port]:
    ports_by_name = {port.name: port for port in header_ports}
    for match in DECL_RE.finditer(strip_comments(body)):
        direction = match.group(1)
        data_type = match.group(2) or ("reg" if direction == "output" else "wire")
        width = parse_width(match.group("width"))
        for name_part in split_top_level(match.group("names")):
            name = clean_name(name_part)
            if is_identifier(name):
                ports_by_name[name] = Port(
                    name=name,
                    direction=direction,
                    width=width,
                    data_type=data_type,
                    description="",
                )
    return list(ports_by_name.values())


def source_location_for_offset(text: str, path: Path, start: int, end: int | None = None) -> SourceLocation:
    line_start = text.count("\n", 0, start) + 1
    line_end = text.count("\n", 0, end if end is not None else start) + 1
    return SourceLocation(str(path), line_start, line_end)


def split_named_connections(text: str) -> dict[str, str]:
    connections: dict[str, str] = {}
    for item in split_top_level(strip_comments(text)):
        item = item.strip()
        match = re.match(r"^\.(?P<name>[a-zA-Z_][a-zA-Z0-9_$]*)\s*\((?P<expr>.*)\)$", item, re.S)
        if match:
            connections[match.group("name")] = " ".join(match.group("expr").split())
    return connections


def parse_instances(body: str, full_text: str, path: Path, body_offset: int, current_module: str) -> list[InstanceInfo]:
    instances: list[InstanceInfo] = []
    clean_body = strip_comments(body)
    for match in INSTANCE_RE.finditer(clean_body):
        module_name = match.group("module")
        instance_name = match.group("instance")
        if module_name in INSTANCE_KEYWORDS:
            continue
        if module_name in {"input", "output", "inout", "wire", "reg", "logic", "parameter", "localparam"}:
            continue
        instances.append(
            InstanceInfo(
                module_name=module_name,
                instance_name=instance_name,
                parameter_overrides=split_named_connections(match.group("params") or ""),
                port_connections=split_named_connections(match.group("ports") or ""),
                source=source_location_for_offset(
                    full_text,
                    path,
                    body_offset + match.start(),
                    body_offset + match.end(),
                ),
            )
        )
    return instances


def detect_clock_candidates(ports: list[PortInfo]) -> list[str]:
    candidates = []
    for port in ports:
        lowered = port.name.lower()
        if port.direction == "input" and (lowered in {"clk", "clock", "aclk"} or "clk" in lowered):
            candidates.append(port.name)
    return candidates


def detect_reset_candidates(ports: list[PortInfo]) -> list[str]:
    candidates = []
    for port in ports:
        lowered = port.name.lower()
        if port.direction == "input" and ("rst" in lowered or "reset" in lowered):
            candidates.append(port.name)
    return candidates


def port_to_info(port: Port, source: SourceLocation) -> PortInfo:
    return PortInfo(port.name, port.direction, port.width, port.data_type, source)


def detect_states(text: str) -> list[str]:
    states = []
    for state in STATE_NAME_RE.findall(text):
        if state not in states and any(token in state for token in ("IDLE", "STATE", "START", "STOP", "WAIT", "DONE", "READ", "WRITE")):
            states.append(state)
    if re.search(r"\bcase\s*\(\s*(state|fsm|current_state|state_reg)\s*\)", text):
        for token in ("IDLE", "START", "DATA", "STOP", "WAIT", "DONE", "READ", "WRITE"):
            if re.search(rf"\b{token}\b", text) and token not in states:
                states.append(token)
    return states[:16]


def compact_expression(text: str, limit: int = 160) -> str:
    compacted = " ".join(text.split())
    if len(compacted) <= limit:
        return compacted
    return compacted[: limit - 3].rstrip() + "..."


def detect_memory_candidates(body: str, full_text: str, path: Path, body_offset: int) -> list[StructuralFact]:
    facts: list[StructuralFact] = []
    for match in MEMORY_DECL_RE.finditer(body):
        facts.append(
            StructuralFact(
                kind="memory_declaration",
                name=match.group("name"),
                expression=compact_expression(match.group(0)),
                source=source_location_for_offset(
                    full_text,
                    path,
                    body_offset + match.start(),
                    body_offset + match.end(),
                ),
            )
        )
    return facts


def detect_always_blocks(body: str, full_text: str, path: Path, body_offset: int) -> list[StructuralFact]:
    facts: list[StructuralFact] = []
    for idx, match in enumerate(ALWAYS_RE.finditer(body), start=1):
        sensitivity = compact_expression(match.group("sensitivity") or "")
        facts.append(
            StructuralFact(
                kind="always_block",
                name=f"always_{idx}",
                expression=sensitivity or "implicit",
                source=source_location_for_offset(
                    full_text,
                    path,
                    body_offset + match.start(),
                    body_offset + match.end(),
                ),
            )
        )
    return facts


def detect_continuous_assignments(body: str, full_text: str, path: Path, body_offset: int) -> list[StructuralFact]:
    facts: list[StructuralFact] = []
    for match in ASSIGN_RE.finditer(body):
        lhs = compact_expression(match.group("lhs"))
        rhs = compact_expression(match.group("rhs"))
        facts.append(
            StructuralFact(
                kind="continuous_assignment",
                name=lhs,
                expression=f"{lhs} = {rhs}",
                source=source_location_for_offset(
                    full_text,
                    path,
                    body_offset + match.start(),
                    body_offset + match.end(),
                ),
            )
        )
    return facts


def detect_assertions(body: str, full_text: str, path: Path, body_offset: int) -> list[StructuralFact]:
    facts: list[StructuralFact] = []
    for idx, match in enumerate(ASSERTION_RE.finditer(body), start=1):
        facts.append(
            StructuralFact(
                kind=f"{match.group('kind')}_statement",
                name=f"{match.group('kind')}_{idx}",
                expression=compact_expression(match.group("expr")),
                source=source_location_for_offset(
                    full_text,
                    path,
                    body_offset + match.start(),
                    body_offset + match.end(),
                ),
            )
        )
    return facts


def parse_modules(path: Path) -> list[ModuleInfo]:
    return [module.to_module_info() for module in parse_modules_with_regex(path)]


def parse_modules_with_regex(path: Path) -> list[ModuleIR]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    modules: list[ModuleIR] = []
    for match in MODULE_RE.finditer(text):
        name = match.group(1)
        next_module = MODULE_RE.search(text, match.end())
        end = next_module.start() if next_module else len(text)
        body = text[match.end() : end]
        body_offset = match.end()
        ports = parse_ansi_ports(match.group("ports"))
        ports = parse_body_ports(body, ports)
        source = source_location_for_offset(text, path, match.start(), end)
        port_infos = [port_to_info(port, source) for port in ports]
        modules.append(
            ModuleIR(
                name=name,
                source_file=str(path),
                parameters=parse_parameter_infos(match.group("params"), source),
                ports=port_infos,
                instances=parse_instances(body, text, path, body_offset, name),
                clock_candidates=detect_clock_candidates(port_infos),
                reset_candidates=detect_reset_candidates(port_infos),
                memory_candidates=detect_memory_candidates(body, text, path, body_offset),
                always_blocks=detect_always_blocks(body, text, path, body_offset),
                continuous_assignments=detect_continuous_assignments(body, text, path, body_offset),
                assertions=detect_assertions(body, text, path, body_offset),
                parse_backend="regex",
                syntax_backend="regex",
                instance_backend="regex",
                parameter_backend="regex",
                port_backend="regex",
                semantic_status="not_run",
                parse_warnings=[],
                comments=extract_comments(text[: match.start()] + body),
                states=detect_states(body),
                source_text=body,
            )
        )
    return modules
