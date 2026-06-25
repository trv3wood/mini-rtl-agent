from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .hierarchy import ModuleHierarchy
from .llm_client import AnnotationResult, SemanticAnnotation, SkillAnnotator, create_annotator
from .models import ModuleIR, SkillCandidate
from .taxonomy import TaxonomyResult, normalize_annotation


@dataclass
class SemanticInput:
    module: str
    project: str
    candidate_kind: str
    parameters: list[str]
    ports: list[dict[str, Any]]
    dependencies: list[str]
    used_by: list[str]
    comments: list[str]
    structural_facts: dict[str, Any]
    source_snippets: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "project": self.project,
            "candidate_kind": self.candidate_kind,
            "parameters": self.parameters,
            "ports": self.ports,
            "dependencies": self.dependencies,
            "used_by": self.used_by,
            "comments": self.comments,
            "structural_facts": self.structural_facts,
            "source_snippets": self.source_snippets,
        }


@dataclass
class AnnotationContext:
    inp: SemanticInput
    raw_annotation: SemanticAnnotation
    result: AnnotationResult
    taxonomy: TaxonomyResult = field(default_factory=lambda: TaxonomyResult(normalized=SemanticAnnotation()))
    merged: dict[str, Any] = field(default_factory=dict)


def build_semantic_input(
    module_ir: ModuleIR,
    candidate: SkillCandidate,
    hierarchy: ModuleHierarchy,
    project_name: str,
) -> SemanticInput:
    used_by: list[str] = []
    for other_name, other_module in hierarchy.modules.items():
        for instance in other_module.instances:
            if instance.module_name == module_ir.name:
                used_by.append(other_name)
                break

    structural_facts = {
        "clock_candidates": module_ir.clock_candidates,
        "reset_candidates": module_ir.reset_candidates,
        "fsm_candidates": module_ir.states,
        "memory_candidates": [f.name for f in module_ir.memory_candidates],
        "always_blocks": len(module_ir.always_blocks),
        "continuous_assignments": len(module_ir.continuous_assignments),
        "assertions": len(module_ir.assertions),
    }

    source_snippets: list[str] = []
    for comment in module_ir.comments[:6]:
        source_snippets.append(comment)

    assign_texts: list[str] = []
    for assign in module_ir.continuous_assignments[:3]:
        assign_texts.append(assign.expression)
    for assign in assign_texts:
        if assign not in source_snippets:
            source_snippets.append(assign)

    return SemanticInput(
        module=module_ir.name,
        project=project_name,
        candidate_kind=candidate.candidate_kind,
        parameters=[param.name for param in module_ir.parameters if param.kind == "parameter"],
        ports=[
            {
                "name": port.name,
                "direction": port.direction,
                "width": str(port.width) if port.width else "1",
            }
            for port in module_ir.ports
        ],
        dependencies=candidate.dependency_modules,
        used_by=sorted(set(used_by)),
        comments=module_ir.comments[:8],
        structural_facts=structural_facts,
        source_snippets=source_snippets[:6],
    )


def annotate_module(
    module_ir: ModuleIR,
    candidate: SkillCandidate,
    hierarchy: ModuleHierarchy,
    project_name: str,
    annotator: SkillAnnotator | None = None,
) -> AnnotationContext:
    if annotator is None:
        annotator = create_annotator()

    inp = build_semantic_input(module_ir, candidate, hierarchy, project_name)
    result = annotator.annotate(inp.to_dict())
    taxonomy = normalize_annotation(result.annotation)
    merged = merge_deterministic_and_semantic(
        module_ir=module_ir,
        candidate=candidate,
        project_name=project_name,
        annotation=taxonomy.normalized,
    )

    return AnnotationContext(
        inp=inp,
        raw_annotation=result.annotation,
        result=result,
        taxonomy=taxonomy,
        merged=merged,
    )


def merge_deterministic_and_semantic(
    module_ir: ModuleIR,
    candidate: SkillCandidate,
    project_name: str,
    annotation: SemanticAnnotation,
) -> dict[str, Any]:
    return {
        "skill_id": candidate.skill_id,
        "name": module_ir.name,
        "granularity": annotation.granularity,
        "project": project_name,
        "core_function": annotation.core_function,
        "algorithm": annotation.algorithm,
        "interface": interface_json_from_annotation(module_ir, annotation),
        "structure": annotation.structure[:4],
        "parameters": [param.name for param in module_ir.parameters if param.kind == "parameter"],
        "dependencies": candidate.dependency_modules,
        "used_by": [],
        "rtl_files": [],
        "keywords": annotation.keywords,
        "_semantic_backend": annotation.core_function,
    }


def interface_json_from_annotation(
    module_ir: ModuleIR,
    annotation: SemanticAnnotation,
) -> dict[str, str]:
    inputs = [port.name for port in module_ir.ports if port.direction == "input"]
    outputs = [port.name for port in module_ir.ports if port.direction == "output"]
    input_str = ", ".join(inputs[:8]) if inputs else "none"
    output_str = ", ".join(outputs[:8]) if outputs else "none"
    return {"input": input_str, "output": output_str}


def make_compact_card_from_skill(skill: dict[str, Any]) -> dict[str, Any]:
    core_function = skill.get("core_function", "")
    algorithm = skill.get("algorithm", "unknown")
    structure = skill.get("structure", [])
    keywords = skill.get("keywords", [])

    interface = skill.get("interface", {})
    interface_sig = interface_signature(interface)

    retrieval_text = (
        f"{core_function}. "
        f"Algorithm: {algorithm}. "
        f"Structure: {', '.join(structure[:4])}. "
        f"Interface: {interface_sig}."
    )

    retrieval_text = _trim_words(retrieval_text, 40)

    return {
        "skill_id": skill.get("skill_id", ""),
        "name": skill.get("name", ""),
        "core_function": core_function,
        "algorithm": algorithm,
        "structure": structure[:4],
        "interface_signature": interface_sig,
        "granularity": skill.get("granularity", "primitive"),
        "project": skill.get("project", ""),
        "keywords": keywords[:10],
        "retrieval_text": retrieval_text,
    }


def interface_signature(interface: dict[str, str]) -> str:
    left = interface.get("input", "unknown")
    right = interface.get("output", "unknown")
    if left == right:
        return left
    return f"{left} -> {right}"


def _trim_words(text: str, max_words: int) -> str:
    import re

    words = re.findall(r"\S+", text)
    return " ".join(words[:max_words])
