from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Parameter:
    name: str
    default: str = ""
    description: str = ""


@dataclass
class Port:
    name: str
    direction: str
    width: str = "1"
    data_type: str = "wire"
    description: str = ""


@dataclass
class ModuleInfo:
    name: str
    source_path: Path
    parameters: list[Parameter] = field(default_factory=list)
    ports: list[Port] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)
    states: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)
    category: str = "rtl"
    interfaces: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    source_text: str = ""


@dataclass
class SkillScore:
    total: int
    metadata_completeness: int
    interface_quality: int
    documentation_quality: int
    verification_quality: int
    template_usability: int
    notes: list[str] = field(default_factory=list)

