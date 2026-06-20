from __future__ import annotations

from .models import ModuleInfo


PATTERN_RULES = {
    "fifo": ("fifo", "queue", "full", "empty", "wr_ptr", "rd_ptr"),
    "arbiter": ("arbiter", "grant", "request", "round_robin", "priority"),
    "synchronizer": ("sync", "synchronizer", "cdc", "async_reg", "gray"),
    "pipeline": ("pipeline", "stage", "valid_reg", "pipe"),
    "handshake": ("ready", "valid", "tready", "tvalid"),
    "counter": ("counter", "count", "cnt"),
    "state machine": ("state", "fsm", "case (state", "case(state"),
    "uart": ("uart", "baud", "txd", "rxd"),
    "spi": ("spi", "sclk", "mosi", "miso", "cs_n"),
    "axi": ("axi", "axis", "tdata", "tvalid", "tready"),
    "memory": ("ram", "mem", "memory", "addr", "we"),
    "cache": ("cache", "tag", "line", "miss", "hit"),
}


CATEGORY_PRIORITY = (
    ("fifo", "buffering"),
    ("uart", "serial"),
    ("spi", "serial_bus"),
    ("axi", "bus"),
    ("arbiter", "control"),
    ("synchronizer", "cdc"),
    ("memory", "memory"),
    ("cache", "memory"),
    ("handshake", "streaming"),
    ("pipeline", "datapath"),
    ("counter", "control"),
    ("state machine", "control"),
)


def classify(module: ModuleInfo) -> ModuleInfo:
    haystack = " ".join(
        [
            module.name,
            module.source_path.name,
            module.source_text[:4000],
            " ".join(port.name for port in module.ports),
        ]
    ).lower()
    patterns = []
    for pattern, hints in PATTERN_RULES.items():
        if any(hint in haystack for hint in hints):
            patterns.append(pattern)
    if module.states and "state machine" not in patterns:
        patterns.append("state machine")

    category = "rtl"
    for pattern, candidate in CATEGORY_PRIORITY:
        if pattern in patterns:
            category = candidate
            break

    interfaces = []
    for name in ("axi", "uart", "spi", "fifo", "cdc", "ready_valid", "memory"):
        if name == "ready_valid":
            if "handshake" in patterns:
                interfaces.append(name)
        elif name == "cdc":
            if "synchronizer" in patterns:
                interfaces.append(name)
        elif name in patterns:
            interfaces.append(name)
    if not interfaces:
        interfaces.append("rtl")

    keywords = sorted(set(patterns + [category] + interfaces + module.name.lower().split("_")))
    module.patterns = patterns
    module.category = category
    module.interfaces = interfaces
    module.keywords = keywords
    return module

