from __future__ import annotations

import argparse
import json
from pathlib import Path

from .benchmark import run_benchmark
from .comparison import compare_benchmark_with_external_skillrouter, compare_with_external_skillrouter
from .external_skillrouter import render_command, run_external_skillrouter_benchmark, run_external_skillrouter_query
from .models import QueryPlan
from .retriever import retrieve_skills
from .reporting import write_skillrouter_benchmark_reports, write_skillrouter_goal_alignment_report
from .router_response import build_router_response
from .skillrouter_export import (
    export_skillrouter_records,
    prepare_skillrouter_benchmark_data,
    prepare_skillrouter_query_data,
    write_jsonl,
)
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
        compact_metrics_line(payload.get("compact_card_metrics", {})),
        "",
        f"{'case':<28}  {'hit@1':>5}  {'mrr@10':>7}  {'first':>5}  ranked",
        "-" * 96,
    ]
    for item in payload["cases"]:
        ranked = ", ".join(item["ranked_skill_ids"][:5])
        first = item["first_relevant_rank"] if item["first_relevant_rank"] is not None else "-"
        lines.append(f"{item['id']:<28}  {item['hit_at_1']:>5.1f}  {item['mrr_at_10']:>7.3f}  {first!s:>5}  {ranked}")
    return "\n".join(lines)


def compact_metrics_line(metrics: dict) -> str:
    return (
        f"compact_cards={int(metrics.get('card_count', 0))}  "
        f"avg_text_length={float(metrics.get('avg_text_length', 0.0)):.1f}  "
        f"keyword_match_rate={float(metrics.get('keyword_match_rate', 0.0)):.3f}"
    )


def render_result_dicts_table(results: list[dict]) -> str:
    lines = [f"{'rank':>4}  {'score':>5}  {'skill':<28}  {'category':<14}  why"]
    lines.append("-" * 96)
    for idx, result in enumerate(results, start=1):
        why = "; ".join(result.get("why_matched", [])[:2])
        lines.append(
            f"{idx:>4}  {int(result.get('score', 0)):>5}  "
            f"{str(result.get('name', '')):<28}  {str(result.get('category', '')):<14}  {why}"
        )
    return "\n".join(lines)


def render_comparison_table(payload: dict) -> str:
    comparison = payload["comparison"]
    lines = [
        f"task_id: {comparison['task_id']}  limit: {comparison['limit']}",
        f"local top1:    {comparison['local_top1']}",
        f"external top1: {comparison['external_top1']}",
        f"semantic scored top1: {comparison['semantic_scored_top1']}",
        f"fused top1:    {comparison['fused_top1']}",
        f"overlap local/external: {', '.join(comparison['local_external_overlap']) or '-'}",
        "",
        "fused ranking:",
        render_result_dicts_table(payload["results"]),
    ]
    return "\n".join(lines)


def render_benchmark_comparison_table(payload: dict) -> str:
    lines = [
        f"cases: {payload['case_count']}  limit: {payload['limit']}",
        f"external_json: {payload['external_json']}",
        "",
        f"{'source':<17}  {'hit@1':>7}  {'mrr@10':>7}  {'recall@5':>8}  {'recall@10':>9}  {'recall@20':>9}",
        "-" * 72,
    ]
    for source in ("local", "external", "semantic_scored", "fused"):
        metrics = payload["metrics"][source]
        lines.append(
            f"{source:<17}  {metrics['hit_at_1']:>7.3f}  {metrics['mrr_at_10']:>7.3f}  "
            f"{metrics['recall_at_5']:>8.3f}  {metrics['recall_at_10']:>9.3f}  {metrics['recall_at_20']:>9.3f}"
        )
    lines.extend(
        [
            "",
            f"{'case':<36}  {'local':>5}  {'external':>8}  {'fused':>5}",
            "-" * 72,
        ]
    )
    for item in payload["cases"]:
        lines.append(
            f"{item['id']:<36}  {rank_or_dash(item['local_first_relevant_rank']):>5}  "
            f"{rank_or_dash(item['external_first_relevant_rank']):>8}  "
            f"{rank_or_dash(item['fused_first_relevant_rank']):>5}"
        )
    return "\n".join(lines)


def rank_or_dash(value: object) -> str:
    return "-" if value is None else str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="skill_retriever", description="Search RTL skills from a query_plan.json.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    search = subparsers.add_parser("search", help="Search skills with a query_plan.json file.")
    search.add_argument("query_plan", help="Path to query_plan.json.")
    search.add_argument("--skills-root", default="skills", help="Directory containing skill packages.")
    search.add_argument("--format", choices=("table", "json"), default="table")
    search.add_argument("--limit", type=int, default=10)

    route = subparsers.add_parser(
        "route",
        help="Return a downstream-agent router response for a query_plan.json.",
    )
    route.add_argument("query_plan", help="Path to query_plan.json.")
    route.add_argument("--skills-root", default="skills", help="Directory containing skill packages.")
    route.add_argument("--external-json", help="Optional external SkillRouter retrieval/reranked JSON to fuse.")
    route.add_argument("--task-id", default="local_query", help="Task id inside external JSON.")
    route.add_argument("--limit", type=int, default=5)

    status = subparsers.add_parser(
        "skillrouter-status",
        help="Report current implementation alignment with GOAL.md Skill Router targets.",
    )
    status.add_argument("--report-md", help="Optional Markdown status report output path.")
    status.add_argument("--report-json", help="Optional JSON status report output path.")
    status.add_argument("--format", choices=("table", "json"), default="table")

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

    prepare_benchmark = subparsers.add_parser(
        "prepare-skillrouter-benchmark",
        help="Prepare a router benchmark as a SkillRouter data_root.",
    )
    prepare_benchmark.add_argument("dataset", help="Benchmark JSON path.")
    prepare_benchmark.add_argument("--skills-root", default="skills", help="Directory containing skill packages.")
    prepare_benchmark.add_argument("--output-dir", required=True, help="Output SkillRouter data_root directory.")
    prepare_benchmark.add_argument("--tier", action="append", choices=("easy", "hard"), help="Tier directory to write. Repeatable; defaults to easy.")

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

    compare = subparsers.add_parser(
        "compare-skillrouter-query",
        help="Compare local retriever, external SkillRouter output, and fused ranking.",
    )
    compare.add_argument("query_plan", help="Path to query_plan.json.")
    compare.add_argument("--skills-root", default="skills", help="Directory containing skill packages.")
    compare.add_argument("--external-json", required=True, help="Path to external SkillRouter retrieval/reranked JSON.")
    compare.add_argument("--task-id", default="local_query", help="Task id inside external JSON.")
    compare.add_argument("--format", choices=("table", "json"), default="table")
    compare.add_argument("--limit", type=int, default=10)

    compare_benchmark = subparsers.add_parser(
        "compare-skillrouter-benchmark",
        help="Compare local, external SkillRouter, and fused metrics on a router benchmark.",
    )
    compare_benchmark.add_argument("dataset", help="Benchmark JSON path.")
    compare_benchmark.add_argument("--skills-root", default="skills", help="Directory containing skill packages.")
    compare_benchmark.add_argument("--external-json", required=True, help="Path to external SkillRouter retrieval/reranked JSON.")
    compare_benchmark.add_argument("--format", choices=("table", "json"), default="table")
    compare_benchmark.add_argument("--limit", type=int, default=10)
    compare_benchmark.add_argument("--report-md", help="Optional Markdown report output path.")
    compare_benchmark.add_argument("--report-json", help="Optional JSON report output path.")

    benchmark = subparsers.add_parser("benchmark", help="Evaluate retriever ranking on a query-plan benchmark JSON.")
    benchmark.add_argument("dataset", help="Benchmark JSON path.")
    benchmark.add_argument("--skills-root", default="skills", help="Directory containing skill packages.")
    benchmark.add_argument("--limit", type=int, default=20)
    benchmark.add_argument("--format", choices=("table", "json"), default="table")

    external = subparsers.add_parser(
        "run-skillrouter-query",
        help="Prepare local skills, optionally run external SkillRouter retrieval, and fuse results.",
    )
    external.add_argument("query_plan", help="Path to query_plan.json.")
    external.add_argument("--skills-root", default="skills", help="Directory containing skill packages.")
    external.add_argument("--external-root", default="external/SkillRouter", help="External SkillRouter checkout.")
    external.add_argument("--work-dir", default="work/skillrouter_query", help="Prepared local SkillRouter data_root.")
    external.add_argument("--output-dir", default="outputs/local_rtl_query", help="Output dir relative to external root.")
    external.add_argument("--task-id", default="local_query", help="Task id for the prepared query.")
    external.add_argument("--tier", choices=("easy", "hard"), default="easy")
    external.add_argument("--mode", choices=("retrieval", "pipeline"), default="retrieval")
    external.add_argument("--dry-run", action="store_true", help="Prepare data and print the external command without running it.")
    external.add_argument("--use-existing", action="store_true", help="Import and fuse the expected external output without running external models.")
    external.add_argument("--format", choices=("table", "json"), default="table")
    external.add_argument("--limit", type=int, default=10)
    external.add_argument("--top-k", type=int, default=20)
    external.add_argument("--encoder-model", default="pipizhao/SkillRouter-Embedding-0.6B")
    external.add_argument("--reranker-model", default="pipizhao/SkillRouter-Reranker-0.6B")
    external.add_argument("--encoder-max-length", type=int, default=1024)
    external.add_argument("--reranker-max-length", type=int, default=1024)
    external.add_argument("--encoder-batch-size", type=int, default=16)
    external.add_argument("--reranker-batch-size", type=int, default=4)

    external_benchmark = subparsers.add_parser(
        "run-skillrouter-benchmark",
        help="Prepare a benchmark, optionally run external SkillRouter, and compare metrics.",
    )
    external_benchmark.add_argument("dataset", help="Benchmark JSON path.")
    external_benchmark.add_argument("--skills-root", default="skills", help="Directory containing skill packages.")
    external_benchmark.add_argument("--external-root", default="external/SkillRouter", help="External SkillRouter checkout.")
    external_benchmark.add_argument("--work-dir", default="work/skillrouter_benchmark", help="Prepared SkillRouter benchmark data_root.")
    external_benchmark.add_argument("--output-dir", default="outputs/local_rtl_benchmark", help="Output dir relative to external root.")
    external_benchmark.add_argument("--tier", choices=("easy", "hard"), default="easy")
    external_benchmark.add_argument("--mode", choices=("retrieval", "pipeline"), default="retrieval")
    external_benchmark.add_argument("--dry-run", action="store_true", help="Prepare data and print external commands without running models.")
    external_benchmark.add_argument("--use-existing", action="store_true", help="Import and compare the expected external output without running models.")
    external_benchmark.add_argument("--format", choices=("table", "json"), default="table")
    external_benchmark.add_argument("--limit", type=int, default=10)
    external_benchmark.add_argument("--report-md", help="Optional Markdown comparison report output path.")
    external_benchmark.add_argument("--report-json", help="Optional JSON comparison report output path.")
    external_benchmark.add_argument("--top-k", type=int, default=20)
    external_benchmark.add_argument("--encoder-model", default="pipizhao/SkillRouter-Embedding-0.6B")
    external_benchmark.add_argument("--reranker-model", default="pipizhao/SkillRouter-Reranker-0.6B")
    external_benchmark.add_argument("--encoder-max-length", type=int, default=1024)
    external_benchmark.add_argument("--reranker-max-length", type=int, default=1024)
    external_benchmark.add_argument("--encoder-batch-size", type=int, default=16)
    external_benchmark.add_argument("--reranker-batch-size", type=int, default=4)

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
    if args.command == "route":
        try:
            plan = load_query_plan(Path(args.query_plan))
            lexical = retrieve_skills(plan, Path(args.skills_root), limit=args.limit)
            if args.external_json:
                semantic = import_skillrouter_results(
                    Path(args.external_json),
                    args.task_id,
                    Path(args.skills_root),
                    plan,
                    limit=args.limit,
                )
                ranked = fuse_rankings(lexical, semantic, limit=args.limit)
            else:
                ranked = lexical
        except ValueError as exc:
            print(f"ERROR: {exc}")
            return 1
        print(json.dumps(build_router_response(plan, ranked, limit=args.limit), indent=2))
        return 0
    if args.command == "skillrouter-status":
        payload, written = write_skillrouter_goal_alignment_report(
            markdown_path=Path(args.report_md) if args.report_md else None,
            json_path=Path(args.report_json) if args.report_json else None,
        )
        if args.format == "json":
            print(json.dumps(payload, indent=2))
        else:
            print(f"goal: {payload['goal']}")
            print(f"status: {payload['status']}")
            print("")
            print("implemented:")
            for item in payload["implemented"]:
                print(f"- {item['requirement']}")
            print("")
            print("boundaries:")
            for item in payload["boundaries"]:
                print(f"- {item}")
            for path in written:
                print(f"wrote report: {path}")
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
    if args.command == "prepare-skillrouter-benchmark":
        try:
            payload = prepare_skillrouter_benchmark_data(
                Path(args.dataset),
                Path(args.skills_root),
                Path(args.output_dir),
                tiers=args.tier or ["easy"],
            )
        except ValueError as exc:
            print(f"ERROR: {exc}")
            return 1
        tiers = " ".join(payload["tiers"])
        print(f"prepared {payload['tasks']} task(s) and {payload['records']} skill(s) under {payload['data_root']}")
        print("run external SkillRouter retrieval with:")
        print(
            "  cd external/SkillRouter && "
            f".venv/bin/python -m src.export_retrieval --encoder_model_or_path "
            f"pipizhao/SkillRouter-Embedding-0.6B --data_root {Path(args.output_dir).resolve()} "
            f"--tiers {tiers} --top_k 20 --max_length 1024 --batch_size 16 "
            f"--output_dir outputs/local_rtl_benchmark"
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
    if args.command == "compare-skillrouter-query":
        try:
            plan = load_query_plan(Path(args.query_plan))
            payload = compare_with_external_skillrouter(
                plan,
                skills_root=Path(args.skills_root),
                external_json=Path(args.external_json),
                task_id=args.task_id,
                limit=args.limit,
            )
        except ValueError as exc:
            print(f"ERROR: {exc}")
            return 1
        if args.format == "json":
            print(json.dumps(payload, indent=2))
        else:
            print(render_comparison_table(payload))
        return 0
    if args.command == "compare-skillrouter-benchmark":
        try:
            payload = compare_benchmark_with_external_skillrouter(
                Path(args.dataset),
                skills_root=Path(args.skills_root),
                external_json=Path(args.external_json),
                limit=args.limit,
            )
            written = write_skillrouter_benchmark_reports(
                payload,
                markdown_path=Path(args.report_md) if args.report_md else None,
                json_path=Path(args.report_json) if args.report_json else None,
            )
        except ValueError as exc:
            print(f"ERROR: {exc}")
            return 1
        if args.format == "json":
            print(json.dumps(payload, indent=2))
        else:
            print(render_benchmark_comparison_table(payload))
            for path in written:
                print(f"wrote report: {path}")
        return 0
    if args.command == "run-skillrouter-query":
        try:
            plan = load_query_plan(Path(args.query_plan))
            payload = run_external_skillrouter_query(
                plan,
                skills_root=Path(args.skills_root),
                external_root=Path(args.external_root),
                work_dir=Path(args.work_dir),
                output_dir=args.output_dir,
                task_id=args.task_id,
                tier=args.tier,
                mode=args.mode,
                limit=args.limit,
                dry_run=args.dry_run,
                use_existing=args.use_existing,
                encoder_model=args.encoder_model,
                reranker_model=args.reranker_model,
                top_k=args.top_k,
                encoder_max_length=args.encoder_max_length,
                reranker_max_length=args.reranker_max_length,
                encoder_batch_size=args.encoder_batch_size,
                reranker_batch_size=args.reranker_batch_size,
            )
        except ValueError as exc:
            print(f"ERROR: {exc}")
            return 1
        written = []
        if payload.get("status") == "ok" and "comparison" in payload:
            written = write_skillrouter_benchmark_reports(
                payload["comparison"],
                markdown_path=Path(args.report_md) if args.report_md else None,
                json_path=Path(args.report_json) if args.report_json else None,
            )
        if args.format == "json":
            print(json.dumps(payload, indent=2))
            return 0
        print(f"prepared {payload['prepared']['records']} skill(s) under {payload['prepared']['data_root']}")
        print(f"external cwd: {payload['cwd']}")
        for idx, command in enumerate(payload.get("commands", [payload["command"]]), start=1):
            print(f"command {idx}: {render_command(command)}")
        print(f"expected result: {payload['expected_result']}")
        if payload.get("dry_run"):
            return 0
        if payload.get("status") != "ok":
            print(f"ERROR: external SkillRouter failed with return code {payload.get('return_code')}")
            if payload.get("stderr"):
                print(payload["stderr"])
            return 1
        print(render_result_dicts_table(payload["fused"]["results"]))
        return 0
    if args.command == "run-skillrouter-benchmark":
        try:
            payload = run_external_skillrouter_benchmark(
                Path(args.dataset),
                skills_root=Path(args.skills_root),
                external_root=Path(args.external_root),
                work_dir=Path(args.work_dir),
                output_dir=args.output_dir,
                tier=args.tier,
                mode=args.mode,
                limit=args.limit,
                dry_run=args.dry_run,
                use_existing=args.use_existing,
                encoder_model=args.encoder_model,
                reranker_model=args.reranker_model,
                top_k=args.top_k,
                encoder_max_length=args.encoder_max_length,
                reranker_max_length=args.reranker_max_length,
                encoder_batch_size=args.encoder_batch_size,
                reranker_batch_size=args.reranker_batch_size,
            )
        except ValueError as exc:
            print(f"ERROR: {exc}")
            return 1
        if args.format == "json":
            print(json.dumps(payload, indent=2))
            return 0
        print(
            f"prepared {payload['prepared']['tasks']} task(s) and "
            f"{payload['prepared']['records']} skill(s) under {payload['prepared']['data_root']}"
        )
        print(f"external cwd: {payload['cwd']}")
        for idx, command in enumerate(payload.get("commands", [payload["command"]]), start=1):
            print(f"command {idx}: {render_command(command)}")
        print(f"expected result: {payload['expected_result']}")
        if payload.get("dry_run"):
            return 0
        if payload.get("status") != "ok":
            print(f"ERROR: external SkillRouter failed with return code {payload.get('return_code')}")
            if payload.get("stderr"):
                print(payload["stderr"])
            if payload.get("rerank_stderr"):
                print(payload["rerank_stderr"])
            return 1
        print(render_benchmark_comparison_table(payload["comparison"]))
        for path in written:
            print(f"wrote report: {path}")
        return 0
    return 1
