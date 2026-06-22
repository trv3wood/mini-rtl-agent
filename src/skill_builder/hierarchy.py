from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .generator import sanitize_skill_name
from .models import DependencyIssue, ModuleIR, SkillCandidate


VENDOR_PRIMITIVES = {
    "BUFG",
    "BUFGCE",
    "IBUF",
    "LUT1",
    "LUT2",
    "LUT3",
    "LUT4",
    "LUT5",
    "LUT6",
    "OBUF",
    "RAMB18E1",
    "RAMB36E1",
    "SB_IO",
    "SB_RAM40_4K",
}
VENDOR_PATTERNS = (
    re.compile(r"^RAMB\d+", re.I),
    re.compile(r"^DSP\d+", re.I),
    re.compile(r"^MMCME\d+", re.I),
    re.compile(r"^PLLE\d+", re.I),
    re.compile(r"^BUFG", re.I),
    re.compile(r"^SB_", re.I),
)
PACKAGE_OR_INTERFACE_HINTS = ("interface", "modport", "package", "pkg")
EXTERNAL_LIBRARY_HINTS = ("ip", "model", "cell", "primitive", "vendor")


@dataclass
class ModuleHierarchy:
    modules: dict[str, ModuleIR] = field(default_factory=dict)
    modules_by_name: dict[str, list[ModuleIR]] = field(default_factory=dict)
    edges: dict[str, set[str]] = field(default_factory=dict)
    roots: list[str] = field(default_factory=list)
    unresolved_dependencies: dict[str, set[str]] = field(default_factory=dict)
    dependency_issues: dict[str, list[DependencyIssue]] = field(default_factory=dict)
    duplicate_modules: dict[str, list[str]] = field(default_factory=dict)
    internal_modules: set[str] = field(default_factory=set)


def classify_dependency_issue(name: str, source_module: str, source_file: str | None) -> DependencyIssue:
    if name in VENDOR_PRIMITIVES or any(pattern.match(name) for pattern in VENDOR_PATTERNS):
        return DependencyIssue(
            name,
            source_module,
            source_file,
            "vendor_primitive",
            "Matches known FPGA primitive naming pattern.",
        )
    lowered = name.lower()
    if any(hint in lowered for hint in PACKAGE_OR_INTERFACE_HINTS):
        return DependencyIssue(
            name,
            source_module,
            source_file,
            "package_or_interface",
            "Name contains package/interface-style hint.",
        )
    if any(hint in lowered for hint in EXTERNAL_LIBRARY_HINTS):
        return DependencyIssue(
            name,
            source_module,
            source_file,
            "external_library",
            "Name suggests an external IP, model, cell, primitive, or vendor library component.",
        )
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_$]*$", name):
        return DependencyIssue(
            name,
            source_module,
            source_file,
            "possible_parser_error",
            "Name is not a plain Verilog identifier; dependency may be a parser artifact.",
        )
    return DependencyIssue(name, source_module, source_file, "unknown", "No conservative classification rule matched.")


def build_module_hierarchy(modules: list[ModuleIR]) -> ModuleHierarchy:
    modules_by_name: dict[str, list[ModuleIR]] = {}
    for module in modules:
        modules_by_name.setdefault(module.name, []).append(module)

    duplicate_modules = {
        name: [module.source_file for module in same_name]
        for name, same_name in modules_by_name.items()
        if len(same_name) > 1
    }
    for name, sources in duplicate_modules.items():
        warning = f"duplicate module definition: {name} in {', '.join(sorted(sources))}"
        for module in modules_by_name[name]:
            module.parse_warnings.append(warning)

    # Keep a compatibility map for callers that expect one representative per name.
    by_name = {name: same_name[0] for name, same_name in modules_by_name.items()}
    edges = {name: set() for name in by_name}
    unresolved: dict[str, set[str]] = {name: set() for name in by_name}
    issues: dict[str, list[DependencyIssue]] = {name: [] for name in by_name}
    instantiated_by_project: set[str] = set()

    for module_name, module in by_name.items():
        for instance in module.instances:
            dependency = instance.module_name
            if dependency in by_name and dependency not in duplicate_modules:
                edges[module_name].add(dependency)
                if dependency != module_name:
                    instantiated_by_project.add(dependency)
                continue
            issue = classify_dependency_issue(dependency, module_name, module.source_file)
            issues[module_name].append(issue)
            if issue.category == "vendor_primitive":
                continue
            unresolved[module_name].add(dependency)

    roots = sorted(name for name in by_name if name not in instantiated_by_project)
    unresolved = {name: deps for name, deps in unresolved.items() if deps}
    issues = {name: module_issues for name, module_issues in issues.items() if module_issues}
    return ModuleHierarchy(
        modules=by_name,
        modules_by_name=modules_by_name,
        edges=edges,
        roots=roots,
        unresolved_dependencies=unresolved,
        dependency_issues=issues,
        duplicate_modules=duplicate_modules,
        internal_modules=instantiated_by_project,
    )


def compute_dependency_closure(root_module: str, hierarchy: ModuleHierarchy) -> SkillCandidate:
    module = hierarchy.modules.get(root_module)
    if module is None:
        return SkillCandidate(
            skill_id=sanitize_skill_name(root_module),
            root_module=root_module,
            root_source="",
            unresolved_dependencies=[root_module],
            candidate_kind="unresolved",
            hierarchy_warnings=[f"root module not found: {root_module}"],
        )

    candidate = SkillCandidate(
        skill_id=sanitize_skill_name(root_module),
        root_module=root_module,
        root_source=module.source_file,
    )
    ordered_dependencies: list[str] = []
    source_files: list[str] = []
    visited: set[str] = set()
    visiting: list[str] = []
    cyclic = False

    def add_source(source_file: str) -> None:
        if source_file not in source_files:
            source_files.append(source_file)

    def visit(name: str) -> None:
        nonlocal cyclic
        if name in visiting:
            cycle = visiting[visiting.index(name) :] + [name]
            candidate.hierarchy_warnings.append(f"cyclic dependency detected: {' -> '.join(cycle)}")
            cyclic = True
            return
        if name in visited:
            return
        visited.add(name)
        current = hierarchy.modules.get(name)
        if current is None:
            return
        add_source(current.source_file)
        visiting.append(name)
        for dependency in sorted(hierarchy.edges.get(name, set())):
            if dependency != root_module and dependency not in ordered_dependencies:
                ordered_dependencies.append(dependency)
            visit(dependency)
        visiting.pop()

    visit(root_module)
    candidate.dependency_modules = ordered_dependencies
    candidate.source_files = source_files

    raw_unresolved: list[str] = []
    dependency_issues: list[DependencyIssue] = []
    for name in [root_module, *ordered_dependencies]:
        raw_unresolved.extend(sorted(hierarchy.unresolved_dependencies.get(name, set())))
        dependency_issues.extend(hierarchy.dependency_issues.get(name, []))
    candidate.dependency_issues = dependency_issues
    candidate.unresolved_dependencies = sorted(set(raw_unresolved))
    candidate.vendor_primitives = sorted(
        {issue.name for issue in dependency_issues if issue.category == "vendor_primitive"}
    )
    candidate.external_dependencies = sorted(
        {
            issue.name
            for issue in dependency_issues
            if issue.category in {"external_library", "package_or_interface", "unknown", "possible_parser_error"}
        }
    )

    if root_module in hierarchy.duplicate_modules:
        candidate.hierarchy_warnings.append(f"duplicate module definition for root: {root_module}")
    for dependency in ordered_dependencies:
        if dependency in hierarchy.duplicate_modules:
            candidate.hierarchy_warnings.append(f"duplicate module definition for dependency: {dependency}")

    candidate.is_self_contained = not candidate.unresolved_dependencies and not any(
        "duplicate module definition" in warning for warning in candidate.hierarchy_warnings
    )
    closure_modules = [root_module, *ordered_dependencies]
    candidate.frontend_backends = sorted(
        {hierarchy.modules[name].parse_backend for name in closure_modules if name in hierarchy.modules}
    )
    candidate.frontend_instance_backends = sorted(
        {hierarchy.modules[name].instance_backend for name in closure_modules if name in hierarchy.modules}
    )
    frontend_warnings: list[str] = []
    for name in closure_modules:
        current = hierarchy.modules.get(name)
        if current is not None:
            frontend_warnings.extend(current.parse_warnings)
    candidate.frontend_warnings = sorted(set(frontend_warnings))
    if cyclic:
        candidate.candidate_kind = "cyclic"
    elif candidate.unresolved_dependencies or not candidate.root_source or root_module in hierarchy.duplicate_modules:
        candidate.candidate_kind = "unresolved"
    elif ordered_dependencies:
        candidate.candidate_kind = "composite"
    else:
        candidate.candidate_kind = "standalone"
    return candidate


def build_skill_candidates(hierarchy: ModuleHierarchy, *, include_internal: bool = False) -> list[SkillCandidate]:
    candidate_names = sorted(hierarchy.modules) if include_internal else hierarchy.roots
    candidates = []
    for module_name in candidate_names:
        duplicate_defs = hierarchy.modules_by_name.get(module_name, [])
        if len(duplicate_defs) > 1:
            for module in duplicate_defs:
                source_hint = sanitize_skill_name(Path(module.source_file).with_suffix("").as_posix())
                candidate = SkillCandidate(
                    skill_id=f"{sanitize_skill_name(module_name)}_{source_hint}",
                    root_module=module_name,
                    root_source=module.source_file,
                    source_files=[module.source_file],
                    unresolved_dependencies=[module_name],
                    candidate_kind="unresolved",
                    hierarchy_warnings=[f"duplicate module definition for root: {module_name}"],
                    frontend_backends=[module.parse_backend],
                    frontend_instance_backends=[module.instance_backend],
                    frontend_warnings=list(module.parse_warnings),
                )
                candidates.append(candidate)
            continue
        candidate = compute_dependency_closure(module_name, hierarchy)
        if include_internal and module_name in hierarchy.internal_modules and candidate.candidate_kind not in {
            "cyclic",
            "unresolved",
        }:
            candidate.candidate_kind = "internal"
        candidates.append(candidate)
    return candidates
