from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def render_skillrouter_benchmark_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# SkillRouter Benchmark Comparison",
        "",
        f"- dataset: `{payload['dataset']}`",
        f"- skills_root: `{payload['skills_root']}`",
        f"- external_json: `{payload['external_json']}`",
        f"- cases: {payload['case_count']}",
        f"- limit: {payload['limit']}",
        "",
        "## Metrics",
        "",
        "| source | Hit@1 | MRR@10 | Recall@5 | Recall@10 | Recall@20 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for source in ("local", "external", "semantic_scored", "fused"):
        metrics = payload["metrics"][source]
        lines.append(
            f"| {source} | {metrics['hit_at_1']:.3f} | {metrics['mrr_at_10']:.3f} | "
            f"{metrics['recall_at_5']:.3f} | {metrics['recall_at_10']:.3f} | {metrics['recall_at_20']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Case Ranks",
            "",
            "| case | relevant | local first | external first | semantic scored first | fused first |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in payload["cases"]:
        relevant = ", ".join(item["relevant_skill_ids"])
        lines.append(
            f"| {item['id']} | {relevant} | {rank_or_dash(item['local_first_relevant_rank'])} | "
            f"{rank_or_dash(item['external_first_relevant_rank'])} | "
            f"{rank_or_dash(item['semantic_scored_first_relevant_rank'])} | "
            f"{rank_or_dash(item['fused_first_relevant_rank'])} |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- `local` is the deterministic lexical/spec-aware retriever.",
            "- `external` is the raw external SkillRouter order imported from JSON.",
            "- `semantic_scored` maps external hits back to local skills and applies local scoring plus semantic rank bonus.",
            "- `fused` merges local and semantic-scored rankings.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_skillrouter_benchmark_reports(
    payload: dict[str, Any],
    *,
    markdown_path: Path | None = None,
    json_path: Path | None = None,
) -> list[Path]:
    written = []
    if markdown_path is not None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_skillrouter_benchmark_markdown(payload), encoding="utf-8")
        written.append(markdown_path)
    if json_path is not None:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        written.append(json_path)
    return written


def skillrouter_goal_alignment_payload() -> dict[str, Any]:
    return {
        "goal": "GOAL.md section 7 Skill Router",
        "status": "external_skillrouter_optional_adapter_integrated",
        "implemented": [
            {
                "requirement": "SkillRouter input can be natural language or structured module contract",
                "current_state": "The deterministic retriever accepts query_plan.json. Natural-language rewriting remains upstream LLM-agent responsibility.",
                "artifacts": ["src/skill_retriever/models.py", "src/skill_retriever/cli.py"],
            },
            {
                "requirement": "Retrieve flattened Skill Spec text rather than raw RTL",
                "current_state": "Local exporter flattens module_info.json, README.md, and skill_spec.json retrieval_text/claims into SkillRouter JSONL records.",
                "artifacts": ["src/skill_retriever/skillrouter_export.py"],
            },
            {
                "requirement": "Use paper SkillRouter embedding retriever",
                "current_state": "Optional adapter prepares local data_root and can invoke external/SkillRouter/src.export_retrieval when explicitly requested.",
                "artifacts": ["src/skill_retriever/external_skillrouter.py", "external/SkillRouter/"],
            },
            {
                "requirement": "Use paper SkillRouter reranker",
                "current_state": "Pipeline mode invokes scripts/skillrouter_rerank_query.py over retrieved local candidates using the external SkillRouter virtualenv.",
                "artifacts": ["scripts/skillrouter_rerank_query.py", "src/skill_retriever/external_skillrouter.py"],
            },
            {
                "requirement": "Combine embedding Top-K and lexical Top-K before final routing",
                "current_state": "External semantic results are imported and fused with deterministic lexical/spec-aware ranking.",
                "artifacts": ["src/skill_retriever/skillrouter_import.py", "src/skill_retriever/comparison.py"],
            },
            {
                "requirement": "Return candidate RTL skills with basis, risk, and adaptation advice",
                "current_state": "route command and route_rtl_skill LangChain tool return selected_skill, candidate_skills, matched_capabilities, required_adaptations, risks, source_path, and ranked results.",
                "artifacts": ["src/skill_retriever/router_response.py", "src/skill_retriever/tools.py"],
            },
            {
                "requirement": "Evaluate Recall@5/10/20, MRR, Hit@1",
                "current_state": "Local and external/fused benchmark comparison reports these metrics and can write Markdown/JSON reports.",
                "artifacts": ["src/skill_retriever/benchmark.py", "src/skill_retriever/comparison.py", "src/skill_retriever/reporting.py"],
            },
        ],
        "commands": [
            "make router-benchmark",
            "make skillrouter-benchmark-dry-run",
            "make skillrouter-report-existing SKILLROUTER_EXTERNAL_JSON=external/SkillRouter/outputs/local_rtl_benchmark/reranked/easy.json",
            "python3 -m skill_retriever route query_plan.json --skills-root skills",
        ],
        "boundaries": [
            "Long GPU model runs remain user-triggered; dry-run prints exact commands to execute manually.",
            "The current seed router benchmark is small and curated; it is regression coverage, not broad router quality evidence.",
            "External SkillRouter official easy/hard summaries are recorded for baseline quality, but local benchmark external results require a separate local data_root run.",
            "The local deterministic retriever is still the default path; external SkillRouter is optional and imported/fused when results exist.",
        ],
        "next_steps": [
            "Run the printed external SkillRouter commands on benchmarks/router_benchmark.json data_root and import real reranked/easy.json.",
            "Increase local benchmark size beyond the 12 seed cases and include more near-miss skills.",
            "Calibrate fusion weights against real external results instead of synthetic smoke JSON.",
        ],
    }


def render_skillrouter_goal_alignment_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# SkillRouter GOAL Alignment",
        "",
        f"- goal: `{payload['goal']}`",
        f"- status: `{payload['status']}`",
        "",
        "## Implemented",
        "",
        "| GOAL requirement | Current state | Artifacts |",
        "| --- | --- | --- |",
    ]
    for item in payload["implemented"]:
        artifacts = "<br>".join(f"`{artifact}`" for artifact in item["artifacts"])
        lines.append(f"| {item['requirement']} | {item['current_state']} | {artifacts} |")
    lines.extend(["", "## Reproduction Commands", ""])
    lines.extend(f"- `{command}`" for command in payload["commands"])
    lines.extend(["", "## Boundaries", ""])
    lines.extend(f"- {item}" for item in payload["boundaries"])
    lines.extend(["", "## Next Steps", ""])
    lines.extend(f"- {item}" for item in payload["next_steps"])
    return "\n".join(lines) + "\n"


def write_skillrouter_goal_alignment_report(
    *,
    markdown_path: Path | None = None,
    json_path: Path | None = None,
) -> tuple[dict[str, Any], list[Path]]:
    payload = skillrouter_goal_alignment_payload()
    written = []
    if markdown_path is not None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_skillrouter_goal_alignment_markdown(payload), encoding="utf-8")
        written.append(markdown_path)
    if json_path is not None:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        written.append(json_path)
    return payload, written


def rank_or_dash(value: object) -> str:
    return "-" if value is None else str(value)
