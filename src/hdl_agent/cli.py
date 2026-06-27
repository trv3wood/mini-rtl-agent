from __future__ import annotations

import argparse
import json
from pathlib import Path

from .workflow import DEFAULT_MAX_RETRIES, DEFAULT_OUTPUT, DEFAULT_SKILLS_ROOT, run_hdl_agent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hdl_agent",
        description="Generate HDL from a natural-language request using an LLM and the RTL skill retriever.",
    )
    parser.add_argument("request", help="Natural-language HDL programming request.")
    parser.add_argument("--skills-root", default=str(DEFAULT_SKILLS_ROOT), help="Skill library root.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Generated HDL output path.")
    parser.add_argument("--output-dir", help="Write a self-contained HDL agent artifact directory.")
    parser.add_argument("--limit", type=int, default=3, help="Retriever result limit.")
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES, help="Maximum syntax-repair retries.")
    parser.add_argument("--emit-spec", action="store_true", help="Emit final_ip_context.json and engineer_spec.json.")
    parser.add_argument("--emit-cpp-ref", action="store_true", help="Emit cpp_model.json and generated C++17 reference files.")
    parser.add_argument("--build-cpp-ref", action="store_true", help="Compile the generated C++17 reference model.")
    parser.add_argument("--run-cpp-ref-tests", action="store_true", help="Run generated C++ reference model unit tests.")
    parser.add_argument(
        "--allow-unsafe-cpp-gen",
        action="store_true",
        help="Allow C++ generation even when cpp_model.json records blocking unknowns/conflicts.",
    )
    parser.add_argument("--show-trace", action="store_true", help="Print query plan and ranked skill names.")
    args = parser.parse_args(argv)

    try:
        result = run_hdl_agent(
            args.request,
            skills_root=Path(args.skills_root),
            output_path=Path(args.output),
            output_dir=Path(args.output_dir) if args.output_dir else None,
            limit=args.limit,
            max_retries=args.max_retries,
            emit_spec=args.emit_spec,
            emit_cpp_ref=args.emit_cpp_ref,
            build_cpp_ref=args.build_cpp_ref,
            run_cpp_ref_tests=args.run_cpp_ref_tests,
            allow_unsafe_cpp_gen=args.allow_unsafe_cpp_gen,
            log=print if args.show_trace or args.output_dir else None,
        )
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    if args.show_trace:
        print("query_plan:")
        print(json.dumps(result.query_plan.to_dict(), indent=2))
        print("retrieved:")
        for index, item in enumerate(result.retrieved["results"], start=1):
            print(f"{index}. {item['name']} score={item['score']} path={item['path']}")
    print(f"selected_skill: {result.selected_skill.name}")
    print(f"syntax_check: passed repair_attempts={result.repair_attempts}")
    print(f"wrote: {result.output_path}")
    return 0
