from __future__ import annotations

import re
from pathlib import Path

from .models import ModuleInfo, Parameter, Port


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
            params.append(Parameter(clean_name(name), default.strip(), "Extracted Verilog parameter."))
        else:
            params.append(Parameter(clean_name(item), "", "Extracted Verilog parameter."))
    return [param for param in params if param.name]


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
                ports.append(Port(clean_name(item), "input", "1", "wire", "Implicit ANSI port."))
                continue
            names = item
        for name_part in split_top_level(names):
            name = clean_name(name_part)
            if name:
                ports.append(
                    Port(
                        name=name,
                        direction=last_direction,
                        width=last_width,
                        data_type=last_type,
                        description=f"{last_direction} port extracted from module header.",
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
            if name:
                ports_by_name[name] = Port(
                    name=name,
                    direction=direction,
                    width=width,
                    data_type=data_type,
                    description=f"{direction} port extracted from declaration.",
                )
    return list(ports_by_name.values())


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


def parse_modules(path: Path) -> list[ModuleInfo]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    modules: list[ModuleInfo] = []
    for match in MODULE_RE.finditer(text):
        name = match.group(1)
        next_module = MODULE_RE.search(text, match.end())
        end = next_module.start() if next_module else len(text)
        body = text[match.end() : end]
        ports = parse_ansi_ports(match.group("ports"))
        ports = parse_body_ports(body, ports)
        modules.append(
            ModuleInfo(
                name=name,
                source_path=path,
                parameters=parse_parameters(match.group("params")),
                ports=ports,
                comments=extract_comments(text[: match.start()] + body),
                states=detect_states(body),
                source_text=body,
            )
        )
    return modules

