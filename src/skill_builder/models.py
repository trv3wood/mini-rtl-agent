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
    functional_summary: str = ""
    structural_summary: str = ""
    behavior_summary: str = ""
    integration_notes: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    use_cases: list[str] = field(default_factory=list)
    source_text: str = ""


@dataclass
class SourceLocation:
    file: str
    line_start: int | None = None
    line_end: int | None = None


@dataclass
class PortInfo:
    name: str
    direction: str
    width: str | int | None
    data_type: str | None
    source: SourceLocation | None = None


@dataclass
class ParameterInfo:
    name: str
    default: str | int | None
    kind: str
    source: SourceLocation | None = None


@dataclass
class InstanceInfo:
    module_name: str
    instance_name: str
    parameter_overrides: dict[str, str] = field(default_factory=dict)
    port_connections: dict[str, str] = field(default_factory=dict)
    source: SourceLocation | None = None


@dataclass
class ModuleIR:
    name: str
    source_file: str
    ports: list[PortInfo] = field(default_factory=list)
    parameters: list[ParameterInfo] = field(default_factory=list)
    instances: list[InstanceInfo] = field(default_factory=list)
    clock_candidates: list[str] = field(default_factory=list)
    reset_candidates: list[str] = field(default_factory=list)
    parse_backend: str = "regex"
    syntax_backend: str = "regex"
    instance_backend: str = "regex"
    parameter_backend: str = "regex"
    port_backend: str = "regex"
    semantic_status: str = "not_run"
    parse_warnings: list[str] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)
    states: list[str] = field(default_factory=list)
    source_text: str = ""

    def to_module_info(self) -> ModuleInfo:
        return ModuleInfo(
            name=self.name,
            source_path=Path(self.source_file),
            parameters=[
                Parameter(
                    name=param.name,
                    default="" if param.default is None else str(param.default),
                    description="",
                )
                for param in self.parameters
                if param.kind == "parameter"
            ],
            ports=[
                Port(
                    name=port.name,
                    direction=port.direction,
                    width="1" if port.width is None else str(port.width),
                    data_type=port.data_type or "wire",
                    description="",
                )
                for port in self.ports
            ],
            comments=self.comments,
            states=self.states,
            source_text=self.source_text,
        )


@dataclass
class DependencyIssue:
    name: str
    source_module: str
    source_file: str | None
    category: str
    reason: str


@dataclass
class SkillCandidate:
    skill_id: str
    root_module: str
    root_source: str
    dependency_modules: list[str] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    unresolved_dependencies: list[str] = field(default_factory=list)
    external_dependencies: list[str] = field(default_factory=list)
    vendor_primitives: list[str] = field(default_factory=list)
    candidate_kind: str = "standalone"
    is_self_contained: bool = False
    hierarchy_warnings: list[str] = field(default_factory=list)
    dependency_issues: list[DependencyIssue] = field(default_factory=list)
    frontend_backends: list[str] = field(default_factory=list)
    frontend_instance_backends: list[str] = field(default_factory=list)
    frontend_warnings: list[str] = field(default_factory=list)


@dataclass
class VerificationStageResult:
    status: str
    command: list[str] = field(default_factory=list)
    return_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0


@dataclass
class VerificationResult:
    source_compile: VerificationStageResult
    generated_tb_compile: VerificationStageResult
    simulation: VerificationStageResult
    failure_stage: str | None = None
    failure_category: str | None = None


@dataclass
class SkillScore:
    total: int
    metadata_completeness: int
    interface_quality: int
    documentation_quality: int
    verification_quality: int
    template_usability: int
    notes: list[str] = field(default_factory=list)
