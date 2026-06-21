from __future__ import annotations


KEYWORD_SKILL_MAP = (
    (("fifo", "queue", "buffer"), "fifo"),
    (("uart", "serial", "receiver", "transmitter"), "uart"),
    (("controller", "control", "fsm", "sequencer"), "fsm"),
    (("clock crossing", "cdc", "synchronizer", "reset sync"), "synchronizer"),
    (("arbiter", "arbitration", "bus grant"), "arbiter"),
    (("dma", "bus", "memory", "register", "wishbone", "axi"), "bus"),
    (("handshake", "ready", "valid", "stream"), "ready_valid"),
    (("rom", "lookup", "twiddle"), "rom"),
    (("multiplier", "multiply", "complex multiply"), "multiplier"),
    (("butterfly", "fft"), "dsp"),
)


def map_node_to_skill_category(name: str, purpose: str = "", patterns: list[str] | None = None) -> str:
    text = " ".join([name, purpose, " ".join(patterns or [])]).lower().replace("_", " ")
    for keywords, category in KEYWORD_SKILL_MAP:
        if any(keyword in text for keyword in keywords):
            return category
    return "custom"


def annotate_submodule(submodule: dict) -> dict:
    annotated = dict(submodule)
    annotated["skill_category"] = map_node_to_skill_category(
        str(submodule.get("name", "")),
        str(submodule.get("purpose", "")),
        [str(item) for item in submodule.get("patterns", [])],
    )
    return annotated
