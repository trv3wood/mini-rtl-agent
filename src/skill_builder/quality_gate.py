from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .models import ModuleIR, SkillCandidate


MAX_RTL_LINES = 500
STATE_CASE_RE = re.compile(
    r"\bcase\s*\(\s*(?P<expr>[A-Za-z_][A-Za-z0-9_$]*(?:\s*\[[^\]]+\])?)\s*\)",
    re.IGNORECASE,
)
STATE_EXPR_HINTS = ("state", "fsm")


@dataclass
class GateDecision:
    accepted: bool
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, int] = field(default_factory=dict)


def evaluate_atomic_skill_candidate(
    candidate: SkillCandidate,
    modules_by_source: dict[str, ModuleIR],
    *,
    max_rtl_lines: int = MAX_RTL_LINES,
) -> GateDecision:
    reasons: list[str] = []
    metrics = {
        "rtl_files": len(candidate.source_files),
        "rtl_lines": 0,
        "state_machines": 0,
        "dependencies": len(candidate.dependency_modules),
    }

    if candidate.dependency_modules:
        reasons.append("not atomic: candidate has dependency modules")
    if candidate.unresolved_dependencies:
        reasons.append("not self-contained: unresolved dependencies")
    if candidate.candidate_kind in {"composite", "cyclic", "unresolved"}:
        reasons.append(f"not atomic: candidate kind is {candidate.candidate_kind}")
    if any("duplicate module definition" in warning for warning in candidate.hierarchy_warnings):
        reasons.append("duplicate module definition")

    for source_file in candidate.source_files:
        module = modules_by_source.get(source_file)
        source_text = module.source_text if module is not None else _read_source(source_file)
        line_count = len(source_text.splitlines())
        metrics["rtl_lines"] += line_count
        metrics["state_machines"] += count_state_machines(source_text)

    if metrics["rtl_lines"] > max_rtl_lines:
        reasons.append(f"RTL exceeds {max_rtl_lines} lines")
    if metrics["state_machines"] > 1:
        reasons.append("contains more than one state machine")
    if not candidate.source_files:
        reasons.append("no RTL source files")

    return GateDecision(accepted=not reasons, reasons=reasons, metrics=metrics)


def count_state_machines(source_text: str) -> int:
    expressions = set()
    for match in STATE_CASE_RE.finditer(source_text):
        expr = match.group("expr").replace(" ", "").lower()
        if any(hint in expr for hint in STATE_EXPR_HINTS):
            expressions.add(expr)
    return len(expressions)


def _read_source(source_file: str) -> str:
    try:
        return Path(source_file).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
