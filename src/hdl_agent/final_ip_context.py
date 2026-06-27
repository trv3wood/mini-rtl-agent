from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True)
class PortFact:
    name: str
    direction: Literal["input", "output", "inout"]
    width: int | str
    signed: bool = False


@dataclass(frozen=True)
class ParameterFact:
    name: str
    value: str | int | None = None


@dataclass(frozen=True)
class ResetCandidate:
    name: str
    polarity: Literal["active_high", "active_low", "unknown"] = "unknown"
    synchronous: bool | Literal["unknown"] = "unknown"


@dataclass(frozen=True)
class FinalRtlFacts:
    module_name: str
    path: Path
    syntax_check: Literal["passed"]
    ports: list[PortFact]
    parameters: list[ParameterFact]
    clock_candidates: list[str]
    reset_candidates: list[ResetCandidate]
    clocking_model: Literal["combinational", "sequential", "unknown"]
    module_header: str
    short_rtl_excerpt: str


def extract_final_rtl_facts(
    rtl_path: Path,
    *,
    syntax_check_status: Literal["passed"],
) -> FinalRtlFacts:
    if syntax_check_status != "passed":
        raise ValueError("final RTL facts can only be extracted after syntax_check_status='passed'")
    text = rtl_path.read_text(encoding="utf-8")
    module_name, header = _extract_first_module_header(text)
    parameters = _extract_parameters(header)
    ports = _extract_ports(header)
    clock_candidates = [port.name for port in ports if port.direction == "input" and _is_clock_name(port.name)]
    reset_candidates = [
        ResetCandidate(
            name=port.name,
            polarity=_reset_polarity(port.name),
            synchronous="unknown",
        )
        for port in ports
        if port.direction == "input" and _is_reset_name(port.name)
    ]
    clocking_model = "sequential" if clock_candidates or re.search(r"\balways_ff\b|always\s*@\s*\(\s*posedge|\balways\s*@\s*\(\s*negedge", text) else "combinational"
    return FinalRtlFacts(
        module_name=module_name,
        path=rtl_path,
        syntax_check="passed",
        ports=ports,
        parameters=parameters,
        clock_candidates=clock_candidates,
        reset_candidates=reset_candidates,
        clocking_model=clocking_model,
        module_header=header.strip(),
        short_rtl_excerpt=_short_excerpt(text, header),
    )


def build_final_ip_context(
    *,
    request: str,
    selected_skill: dict[str, Any],
    final_rtl_facts: FinalRtlFacts,
    output_dir: Path,
    query_plan_path: Path | None,
    retrieval_trace_path: Path | None,
) -> dict[str, Any]:
    card = selected_skill.get("compact_card", {})
    return {
        "schema_version": "final_ip_context.v1",
        "request": request,
        "selected_skill": {
            "skill_id": str(selected_skill.get("skill_id") or selected_skill.get("name") or ""),
            "skill_dir": str(selected_skill.get("skill_dir") or selected_skill.get("path") or ""),
            "score": float(selected_skill.get("score", 0.0)),
            "name": str(selected_skill.get("name") or selected_skill.get("skill_id") or ""),
            "compact_card": {
                "skill_id": str(card.get("skill_id") or card.get("name") or ""),
                "name": str(card.get("name") or card.get("skill_id") or ""),
                "project": str(card.get("project") or ""),
                "category": card.get("category"),
                "granularity": card.get("granularity"),
                "core_function": str(card.get("core_function") or ""),
                "algorithm": card.get("algorithm"),
                "interface_signature": card.get("interface_signature"),
                "structure": [str(item) for item in card.get("structure", [])],
                "keywords": [str(item) for item in card.get("keywords", [])],
                "retrieval_text": str(card.get("retrieval_text") or ""),
            },
        },
        "final_rtl": {
            "module_name": final_rtl_facts.module_name,
            "path": str(final_rtl_facts.path),
            "syntax_check": final_rtl_facts.syntax_check,
            "ports": [asdict(port) for port in final_rtl_facts.ports],
            "parameters": [asdict(parameter) for parameter in final_rtl_facts.parameters],
            "clock_candidates": final_rtl_facts.clock_candidates,
            "reset_candidates": [asdict(reset) for reset in final_rtl_facts.reset_candidates],
            "clocking_model": final_rtl_facts.clocking_model,
            "module_header": final_rtl_facts.module_header,
            "short_rtl_excerpt": final_rtl_facts.short_rtl_excerpt,
        },
        "artifact_paths": {
            "query_plan": str(query_plan_path) if query_plan_path else "",
            "retrieval_trace": str(retrieval_trace_path) if retrieval_trace_path else "",
            "rtl": str(final_rtl_facts.path),
            "engineer_spec": str(output_dir / "engineer_spec.json"),
            "cpp_model": str(output_dir / "cpp_model.json"),
            "cpp_dir": str(output_dir / "cpp"),
        },
    }


def write_final_ip_context(context: dict[str, Any], output_path: Path) -> Path:
    _require(context, ["schema_version", "request", "selected_skill", "final_rtl", "artifact_paths"])
    if context["schema_version"] != "final_ip_context.v1":
        raise ValueError("final_ip_context.schema_version must be final_ip_context.v1")
    final_rtl = context["final_rtl"]
    _require(final_rtl, ["module_name", "path", "syntax_check", "ports", "parameters", "module_header"])
    if final_rtl["syntax_check"] != "passed":
        raise ValueError("final_ip_context.final_rtl.syntax_check must be passed")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(context, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def _extract_first_module_header(text: str) -> tuple[str, str]:
    match = re.search(r"\bmodule\s+([A-Za-z_][A-Za-z0-9_$]*)\b", text)
    if not match:
        raise ValueError("could not find a Verilog module declaration")
    start = match.start()
    index = match.end()
    depth = 0
    while index < len(text):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == ";" and depth == 0:
            return match.group(1), text[start : index + 1]
        index += 1
    raise ValueError("could not find end of first module header")


def _extract_parameters(header: str) -> list[ParameterFact]:
    params_match = re.search(r"#\s*\((.*)\)\s*\(", header, flags=re.S)
    if not params_match:
        return []
    parameters: list[ParameterFact] = []
    for item in _split_top_level_commas(params_match.group(1)):
        item = item.strip()
        match = re.search(r"\bparameter(?:\s+\w+)*\s+([A-Za-z_][A-Za-z0-9_$]*)\s*(?:=\s*(.*))?$", item, flags=re.S)
        if match:
            raw_value = (match.group(2) or "").strip()
            parameters.append(ParameterFact(name=match.group(1), value=_parse_scalar_value(raw_value)))
    return parameters


def _extract_ports(header: str) -> list[PortFact]:
    port_blob_match = re.search(r"\)\s*\((.*)\s*\)\s*;", header, flags=re.S)
    if "#(" not in header:
        port_blob_match = re.search(r"\bmodule\s+[A-Za-z_][A-Za-z0-9_$]*\s*\((.*)\s*\)\s*;", header, flags=re.S)
    if not port_blob_match:
        return []
    ports: list[PortFact] = []
    current_direction: str | None = None
    current_width: int | str = 1
    current_signed = False
    for raw in _split_top_level_commas(port_blob_match.group(1)):
        item = " ".join(raw.strip().split())
        if not item:
            continue
        match = re.match(
            r"(?:(input|output|inout)\s+)?(?:(wire|reg|logic)\s+)?(?:(signed)\s+)?(\[[^\]]+\]\s+)?(.+)$",
            item,
        )
        if not match:
            continue
        direction = match.group(1) or current_direction
        if direction is None:
            continue
        width = _parse_width(match.group(4).strip() if match.group(4) else "") if match.group(4) else current_width
        signed = bool(match.group(3)) if match.group(3) else current_signed
        name_part = match.group(5).strip()
        name_match = re.match(r"([A-Za-z_][A-Za-z0-9_$]*)", name_part)
        if not name_match:
            continue
        current_direction = direction
        current_width = width
        current_signed = signed
        ports.append(PortFact(name=name_match.group(1), direction=direction, width=width, signed=signed))  # type: ignore[arg-type]
    return ports


def _split_top_level_commas(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    paren_depth = 0
    bracket_depth = 0
    brace_depth = 0
    for index, char in enumerate(text):
        if char == "(":
            paren_depth += 1
        elif char == ")":
            paren_depth = max(0, paren_depth - 1)
        elif char == "[":
            bracket_depth += 1
        elif char == "]":
            bracket_depth = max(0, bracket_depth - 1)
        elif char == "{":
            brace_depth += 1
        elif char == "}":
            brace_depth = max(0, brace_depth - 1)
        elif char == "," and paren_depth == 0 and bracket_depth == 0 and brace_depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return parts


def _parse_width(width: str) -> int | str:
    if not width:
        return 1
    match = re.match(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", width)
    if match:
        left = int(match.group(1))
        right = int(match.group(2))
        return abs(left - right) + 1
    return width


def _parse_scalar_value(raw_value: str) -> str | int | None:
    if not raw_value:
        return None
    if re.fullmatch(r"\d+", raw_value):
        return int(raw_value)
    return raw_value


def _is_clock_name(name: str) -> bool:
    lower = name.lower()
    return lower in {"clk", "clock", "aclk"} or lower.endswith("_clk")


def _is_reset_name(name: str) -> bool:
    lower = name.lower()
    return lower in {"rst", "reset", "arst", "srst", "rst_n", "reset_n"} or "reset" in lower or lower.endswith("_rst")


def _reset_polarity(name: str) -> Literal["active_high", "active_low", "unknown"]:
    lower = name.lower()
    if lower.endswith("_n") or lower.startswith("n"):
        return "active_low"
    if lower in {"rst", "reset", "arst", "srst"} or "reset" in lower or "rst" in lower:
        return "active_high"
    return "unknown"


def _short_excerpt(text: str, header: str, *, max_lines: int = 80) -> str:
    lines = text.splitlines()
    header_start = next((idx for idx, line in enumerate(lines) if "module " in line), 0)
    excerpt = lines[header_start : header_start + max_lines]
    if not excerpt:
        return header.strip()
    return "\n".join(excerpt).strip()


def _require(mapping: dict[str, Any], keys: list[str]) -> None:
    missing = [key for key in keys if key not in mapping]
    if missing:
        raise ValueError(f"missing required key(s): {', '.join(missing)}")
