from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from src.utils.llm import ChatClient

from .models import ModuleInfo, SkillCandidate, VerificationResult


SPEC_SCHEMA_VERSION = "skill-spec-v1"
ClaimStatus = Literal["observed", "inferred", "validated", "unknown", "conflicted"]


class SkillClaim(BaseModel):
    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    status: ClaimStatus
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[str]
    conditions: list[str] = Field(default_factory=list)


class SemanticSkillSpec(BaseModel):
    claims: list[SkillClaim]
    unknowns: list[str] = Field(default_factory=list)
    retrieval_text: str = ""


def generate_skill_spec(
    module: ModuleInfo,
    candidate: SkillCandidate,
    evidence_pack: dict,
    verification: VerificationResult,
    tier: str,
    llm: ChatClient,
    cache_dir: Path | None = None,
) -> dict:
    cache_path = spec_cache_path(module, candidate, evidence_pack, cache_dir)
    if cache_path is not None and cache_path.exists():
        semantic = SemanticSkillSpec.model_validate_json(cache_path.read_text(encoding="utf-8"))
    else:
        semantic = llm.complete_structured(
            [
                {
                    "role": "system",
                    "content": (
                        "You generate evidence-linked RTL Skill Specs. "
                        "Every semantic claim must cite only provided evidence_ids. "
                        "Use status='inferred' for semantic interpretation, 'unknown' when evidence is weak, "
                        "and never mark behavior or protocol correctness as validated unless the evidence explicitly validates it. "
                        "Do not invent latency, throughput, depth, or guarantees."
                    ),
                },
                {
                    "role": "user",
                    "content": spec_context(module, candidate, evidence_pack),
                },
            ],
            SemanticSkillSpec,
            temperature=0.0,
        )
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache_path.with_name(f".{cache_path.name}.tmp")
            tmp.write_text(semantic.model_dump_json(indent=2) + "\n", encoding="utf-8")
            tmp.replace(cache_path)

    evidence_id_set = {item["id"] for item in evidence_pack.get("evidence", [])}
    validate_claim_evidence(semantic.claims, evidence_id_set)

    deterministic_claims = deterministic_claims_from_tools(module, evidence_pack, verification, tier)
    claims = [claim.model_dump() for claim in semantic.claims] + deterministic_claims
    unknowns = semantic.unknowns + [
        "Functional equivalence to the original RTL is unverified.",
        "Precise latency, throughput, and protocol guarantees are unknown unless explicitly validated by source tests, assertions, or formal checks.",
    ]

    return {
        "schema_version": "0.1",
        "semantic_schema_version": SPEC_SCHEMA_VERSION,
        "skill_id": candidate.skill_id,
        "root_module": candidate.root_module,
        "category": module.category,
        "interfaces": module.interfaces,
        "patterns": module.patterns,
        "keywords": module.keywords,
        "claims": claims,
        "unknowns": dedupe_preserve_order(unknowns),
        "retrieval_text": semantic.retrieval_text.strip() or retrieval_text(module, semantic.claims),
    }


def spec_context(module: ModuleInfo, candidate: SkillCandidate, evidence_pack: dict) -> str:
    compact_evidence = [
        {
            "id": item.get("id"),
            "type": item.get("type"),
            "status": item.get("status"),
            "name": item.get("name"),
            "value": item.get("value"),
            "direction": item.get("direction"),
            "width": item.get("width"),
            "module_name": item.get("module_name"),
            "instance_name": item.get("instance_name"),
            "stage": item.get("stage"),
            "result": item.get("result"),
        }
        for item in evidence_pack.get("evidence", [])
    ]
    payload = {
        "schema_version": SPEC_SCHEMA_VERSION,
        "module": module.name,
        "category": module.category,
        "interfaces": module.interfaces,
        "patterns": module.patterns,
        "keywords": module.keywords,
        "dependency_modules": candidate.dependency_modules,
        "classifier_summaries": {
            "functional_summary": module.functional_summary,
            "structural_summary": module.structural_summary,
            "behavior_summary": module.behavior_summary,
            "integration_notes": module.integration_notes,
            "limitations": module.limitations,
            "use_cases": module.use_cases,
        },
        "available_evidence": compact_evidence,
        "instructions": {
            "claims": "Return concise function, structure, behavior/interface, constraint, and use-case claims when supported.",
            "evidence_ids": "Use only IDs listed in available_evidence.",
            "unknowns": "List unsupported or unverified facts instead of guessing.",
            "retrieval_text": "Flatten name, role, function, interfaces, behavior, constraints, parameters, verification goals, and keywords for retrieval.",
        },
    }
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


def deterministic_claims_from_tools(
    module: ModuleInfo,
    evidence_pack: dict,
    verification: VerificationResult,
    tier: str,
) -> list[dict]:
    verify_ids = evidence_ids(evidence_pack, "E_VERIFY")
    param_ids = evidence_ids(evidence_pack, "E_PARAM")
    claims = [
        SkillClaim(
            id="C_VERIFY_001",
            kind="verification",
            claim=(
                f"Source compile: {verification.source_compile.status}; generated TB compile: "
                f"{verification.generated_tb_compile.status}; smoke simulation: {verification.simulation.status}; "
                f"quality tier: {tier}."
            ),
            status="validated" if verification.source_compile.status == "passed" else "unknown",
            confidence=0.95 if verification.source_compile.status == "passed" else 0.3,
            evidence_ids=verify_ids,
            conditions=["See tool_runs/*.json for command, stdout, stderr, return code, and duration."],
        ).model_dump()
    ]
    if module.parameters:
        claims.append(
            SkillClaim(
                id="C_PARAM_001",
                kind="customization",
                claim="Detected customizable parameters: "
                + ", ".join(f"{parameter.name}={parameter.default or 'unspecified'}" for parameter in module.parameters)
                + ".",
                status="observed",
                confidence=0.95,
                evidence_ids=param_ids,
                conditions=["Changing parameters requires source compile and smoke simulation."],
            ).model_dump()
        )
    return claims


def validate_claim_evidence(claims: list[SkillClaim], evidence_id_set: set[str]) -> None:
    for claim in claims:
        unknown = sorted(set(claim.evidence_ids) - evidence_id_set)
        if unknown:
            raise ValueError(f"claim {claim.id} references unknown evidence ids: {', '.join(unknown)}")


def evidence_ids(evidence_pack: dict, *prefixes: str) -> list[str]:
    return [
        item["id"]
        for item in evidence_pack.get("evidence", [])
        if any(item["id"].startswith(prefix) for prefix in prefixes)
    ]


def retrieval_text(module: ModuleInfo, claims: list[SkillClaim]) -> str:
    return "\n".join(
        item
        for item in (
            module.name,
            module.category,
            " ".join(module.interfaces),
            " ".join(module.patterns),
            " ".join(module.keywords),
            *(claim.claim for claim in claims),
        )
        if item
    )


def spec_cache_path(
    module: ModuleInfo,
    candidate: SkillCandidate,
    evidence_pack: dict,
    cache_dir: Path | None,
) -> Path | None:
    if cache_dir is None:
        return None
    payload = json.dumps(
        {
            "schema_version": SPEC_SCHEMA_VERSION,
            "module": module.name,
            "skill_id": candidate.skill_id,
            "category": module.category,
            "interfaces": module.interfaces,
            "patterns": module.patterns,
            "keywords": module.keywords,
            "summaries": {
                "functional": module.functional_summary,
                "structural": module.structural_summary,
                "behavior": module.behavior_summary,
            },
            "evidence": evidence_pack.get("evidence", []),
        },
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return cache_dir / f"{module.name}_spec_{digest[:16]}.json"


def dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
