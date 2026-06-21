from __future__ import annotations

import argparse
import json
from pathlib import Path

from .models import QueryPlan
from .retriever import retrieve_skills


def load_query_plan(path: Path) -> QueryPlan:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="skill_retriever", description="Search RTL skills from a query_plan.json.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    search = subparsers.add_parser("search", help="Search skills with a query_plan.json file.")
    search.add_argument("query_plan", help="Path to query_plan.json.")
    search.add_argument("--skills-root", default="skills", help="Directory containing skill packages.")
    search.add_argument("--format", choices=("table", "json"), default="table")
    search.add_argument("--limit", type=int, default=10)

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
    return 1

