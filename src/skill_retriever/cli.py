from __future__ import annotations

import argparse
import json
from pathlib import Path

from .benchmark import run_benchmark
from .models import QueryPlan
from .retriever import retrieve_skills
from .skillrouter_export import export_skillrouter_records, prepare_skillrouter_query_data, write_jsonl
from .skillrouter_import import fused_payload, fuse_rankings, import_skillrouter_results


def load_query_plan(path: Path) -> QueryPlan:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"query_plan not found or unreadable: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid query_plan JSON: {exc}") from exc
    return QueryPlan.from_dict(data)


def result_payload(plan: QueryPlan, results: list) -> dict:
    return {
        "query_plan": plan.to_dict(),
        "results": [result.to_dict() for result in results],
    }


def render_table(results: list) -> str:
    lines = [f"{'rank':>4}  {'score':>5}  {'skill':<28}  {'category':<14}  why"]
    lines.append("-" * 96)
    for idx, result in enumerate(results, start=1):
        why = "; ".join(result.why_matched[:2])
        lines.append(f"{idx:>4}  {result.score:>5}  {result.name:<28}  {result.category:<14}  {why}")
    return "\n".join(lines)


def render_benchmark_table(payload: dict) -> str:
    metrics = payload["metrics"]
    lines = [
        f"cases: {payload['case_count']}  limit: {payload['limit']}",
        f"hit@1={metrics['hit_at_1']:.3f}  mrr@10={metrics['mrr_at_10']:.3f}  "
        f"recall@5={metrics['recall_at_5']:.3f}  recall@10={metrics['recall_at_10']:.3f}  "
        f"recall@20={metrics['recall_at_20']:.3f}",
        "",
        f"{'case':<28}  {'hit@1':>5}  {'mrr@10':>7}  {'first':>5}  ranked",
        "-" * 96,
    ]
    for item in payload["cases"]:
        ranked = ", ".join(item["ranked_skill_ids"][:5])
        first = item["first_relevant_rank"] if item["first_relevant_rank"] is not None else "-"
        lines.append(f"{item['id']:<28}  {item['hit_at_1']:>5.1f}  {item['mrr_at_10']:>7.3f}  {first!s:>5}  {ranked}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="skill_retriever", description="Search RTL skills from a query_plan.json.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    search = subparsers.add_parser("search", help="Search skills with a query_plan.json file.")
    search.add_argument("query_plan", help="Path to query_plan.json.")
    search.add_argument("--skills-root", default="skills", help="Directory containing skill packages.")
    search.add_argument("--format", choices=("table", "json"), default="table")
    search.add_argument("--limit", type=int, default=10)

    export_pool = subparsers.add_parser(
        "export-skillrouter-pool",
        help="Export local RTL skills to SkillRouter-compatible JSONL skill pool.",
    )
    export_pool.add_argument("--skills-root", default="skills", help="Directory containing skill packages.")
    export_pool.add_argument("--output", required=True, help="Output JSONL path.")

    prepare_query = subparsers.add_parser(
        "prepare-skillrouter-query",
        help="Prepare a local query_plan.json and local skills as a SkillRouter data_root.",
    )
    prepare_query.add_argument("query_plan", help="Path to query_plan.json.")
    prepare_query.add_argument("--skills-root", default="skills", help="Directory containing skill packages.")
    prepare_query.add_argument("--output-dir", required=True, help="Output SkillRouter data_root directory.")
    prepare_query.add_argument("--tier", action="append", choices=("easy", "hard"), help="Tier directory to write. Repeatable; defaults to easy.")
    prepare_query.add_argument("--task-id", default="local_query", help="Task id for tasks.jsonl.")

    fuse = subparsers.add_parser(
        "fuse-skillrouter-results",
        help="Fuse local retriever results with external SkillRouter retrieval JSON.",
    )
    fuse.add_argument("query_plan", help="Path to query_plan.json.")
    fuse.add_argument("--skills-root", default="skills", help="Directory containing skill packages.")
    fuse.add_argument("--retrieval-json", required=True, help="Path to external SkillRouter retrieval/<tier>.json.")
    fuse.add_argument("--task-id", default="local_query", help="Task id inside retrieval JSON.")
    fuse.add_argument("--format", choices=("table", "json"), default="json")
    fuse.add_argument("--limit", type=int, default=10)

    benchmark = subparsers.add_parser("benchmark", help="Evaluate retriever ranking on a query-plan benchmark JSON.")
    benchmark.add_argument("dataset", help="Benchmark JSON path.")
    benchmark.add_argument("--skills-root", default="skills", help="Directory containing skill packages.")
    benchmark.add_argument("--limit", type=int, default=20)
    benchmark.add_argument("--format", choices=("table", "json"), default="table")

    args = parser.parse_args(argv)
    if args.command == "search":
        try:
            plan = load_query_plan(Path(args.query_plan))
            results = retrieve_skills(plan, Path(args.skills_root), limit=args.limit)
        except ValueError as exc:
            print(f"ERROR: {exc}")
            return 1
        if args.format == "json":
            print(json.dumps(result_payload(plan, results), indent=2))
        else:
            print(render_table(results))
        return 0
    if args.command == "export-skillrouter-pool":
        records = export_skillrouter_records(Path(args.skills_root))
        write_jsonl(records, Path(args.output))
        print(f"exported {len(records)} skill(s) to {args.output}")
        return 0
    if args.command == "prepare-skillrouter-query":
        try:
            plan = load_query_plan(Path(args.query_plan))
            payload = prepare_skillrouter_query_data(
                plan,
                Path(args.skills_root),
                Path(args.output_dir),
                tiers=args.tier or ["easy"],
                task_id=args.task_id,
            )
        except ValueError as exc:
            print(f"ERROR: {exc}")
            return 1
        tiers = " ".join(payload["tiers"])
        print(f"prepared {payload['records']} skill(s) under {payload['data_root']}")
        print("run external SkillRouter retrieval with:")
        print(
            "  cd external/SkillRouter && "
            f".venv/bin/python -m src.export_retrieval --encoder_model_or_path "
            f"pipizhao/SkillRouter-Embedding-0.6B --data_root {Path(args.output_dir).resolve()} "
            f"--tiers {tiers} --top_k 20 --max_length 1024 --batch_size 16 "
            f"--output_dir outputs/local_rtl_query"
        )
        return 0
    if args.command == "fuse-skillrouter-results":
        try:
            plan = load_query_plan(Path(args.query_plan))
            lexical = retrieve_skills(plan, Path(args.skills_root), limit=args.limit)
            semantic = import_skillrouter_results(
                Path(args.retrieval_json),
                args.task_id,
                Path(args.skills_root),
                plan,
                limit=args.limit,
            )
            fused = fuse_rankings(lexical, semantic, limit=args.limit)
        except ValueError as exc:
            print(f"ERROR: {exc}")
            return 1
        if args.format == "table":
            print(render_table(fused))
        else:
            print(json.dumps(fused_payload(plan, lexical, semantic, fused), indent=2))
        return 0
    if args.command == "benchmark":
        try:
            payload = run_benchmark(Path(args.dataset), Path(args.skills_root), limit=args.limit)
        except ValueError as exc:
            print(f"ERROR: {exc}")
            return 1
        if args.format == "json":
            print(json.dumps(payload, indent=2))
        else:
            print(render_benchmark_table(payload))
        return 0
    return 1
