from __future__ import annotations

import re
from dataclasses import dataclass, field

from .llm_client import SemanticAnnotation


TERM_NORMALIZATION: dict[str, str] = {
    "round robin": "round_robin",
    "round-robin": "round_robin",
    "roundrobin": "round_robin",
    "fixed priority": "fixed_priority",
    "fixed-priority": "fixed_priority",
    "ready valid": "ready_valid",
    "ready-valid": "ready_valid",
    "axi stream": "axi_stream",
    "axi-stream": "axi_stream",
    "wish bone": "wishbone",
    "shift register": "shift_register",
    "shift-register": "shift_register",
    "first word fall through": "fwft",
    "first-word-fall-through": "fwft",
    "width conversion": "width_conversion",
    "width-conversion": "width_conversion",
    "clock domain crossing": "cdc",
    "clock-domain-crossing": "cdc",
    "dual clock": "dual_clock",
    "dual-clock": "dual_clock",
    "single clock": "single_clock",
    "single-clock": "single_clock",
    "one hot": "onehot",
    "one-hot": "onehot",
    "look up table": "lut",
    "look-up-table": "lut",
    "finite state machine": "fsm",
    "finite-state-machine": "fsm",
    "credit based": "credit_based",
    "credit-based": "credit_based",
    "elastic buffer": "elastic_buffer",
    "elastic-buffer": "elastic_buffer",
    "back pressure": "backpressure",
    "back-pressure": "backpressure",
    "skid buffer": "skid_buffer",
    "skid-buffer": "skid_buffer",
    "pipeline register": "pipeline_register",
    "pipeline-register": "pipeline_register",
    "shallow fifo": "shallow_fifo",
    "shallow-fifo": "shallow_fifo",
}

SAFE_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass
class TaxonomyResult:
    normalized: SemanticAnnotation
    unmapped_terms: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def normalize_annotation(annotation: SemanticAnnotation) -> TaxonomyResult:
    unmapped: list[str] = []
    warnings: list[str] = []

    norm = SemanticAnnotation(
        core_function=annotation.core_function.strip(),
        algorithm=annotation.algorithm.strip(),
        structure=[],
        interface_protocol=annotation.interface_protocol.strip(),
        granularity=annotation.granularity.strip(),
        keywords=[],
    )

    norm.structure = _normalize_list(annotation.structure, max_items=4, unmapped=unmapped)
    norm.keywords = _normalize_list(annotation.keywords, max_items=10, unmapped=unmapped)

    if norm.granularity not in {"primitive", "leaf", "composite"}:
        warnings.append(f"invalid granularity '{norm.granularity}', defaulting to 'primitive'")
        norm.granularity = "primitive"

    norm.core_function = _word_limit(norm.core_function, 18)
    norm.algorithm = _word_limit(norm.algorithm, 16)

    return TaxonomyResult(normalized=norm, unmapped_terms=unmapped, warnings=warnings)


def _normalize_list(items: list[str], max_items: int, unmapped: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        raw = str(item).strip().lower()
        if not raw:
            continue
        mapped = TERM_NORMALIZATION.get(raw, raw)
        mapped = _collapse_underscore(mapped)
        if not SAFE_IDENTIFIER_RE.match(mapped.replace("-", "_")):
            mapped = re.sub(r"[^a-z0-9_]+", "_", mapped).strip("_")
        if not mapped:
            continue
        if raw != mapped:
            unmapped.append(f"{raw} -> {mapped}")
        if mapped in seen:
            continue
        seen.add(mapped)
        normalized.append(mapped)
        if len(normalized) >= max_items:
            break
    return normalized


def _collapse_underscore(text: str) -> str:
    return re.sub(r"_+", "_", text).strip("_")


def _word_limit(text: str, max_words: int) -> str:
    words = re.findall(r"\S+", text)
    return " ".join(words[:max_words])
