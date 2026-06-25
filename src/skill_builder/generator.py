from __future__ import annotations

import re


def sanitize_skill_name(name: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_]+", "_", name.strip())
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    return sanitized or "unnamed_skill"
