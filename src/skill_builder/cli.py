from __future__ import annotations

import argparse
import os
import random
from pathlib import Path

from .builder import SkillBuilderError, build_skill_library
from .llm_client import OpenAICompatibleAnnotator
from src.utils.llm import OpenAICompatibleLLM
from src.utils.llm_recording import LLMReplayConfig, RecordingReplayLLM


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="skill_builder", description="Build RTL skills from a Verilog repository.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Build a skill library from a repository.")
    build_parser.add_argument("repo_path", help="Path to a repository containing Verilog/SystemVerilog RTL.")
    build_parser.add_argument(
        "--output",
        default="work/built_skills",
        help="Output directory for generated skills. Defaults to ./work/built_skills.",
    )
    build_parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove previously generated skill directories in the output before rebuilding.",
    )
    build_parser.add_argument(
        "--candidate-mode",
        choices=("all", "roots"),
        default="all",
        help="Select skill candidates: all modules for compatibility, or root modules only.",
    )
    build_parser.add_argument("--record-llm", help="Append LLM calls and raw responses to a JSONL file.")
    build_parser.add_argument("--replay-llm", help="Replay LLM calls from a JSONL file and forbid live LLM calls.")
    build_parser.add_argument(
        "--demo-freeze",
        action="store_true",
        help="Use stable demo metadata for record/replay output.",
    )
    build_parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output for terminal recordings.",
    )
    args = parser.parse_args(argv)
    if args.command == "build":
        if args.record_llm and args.replay_llm:
            print("ERROR: --record-llm and --replay-llm are mutually exclusive")
            return 2
        if args.demo_freeze:
            random.seed(0)
            os.environ.setdefault("PYTHONHASHSEED", "0")
        if args.no_color:
            os.environ["NO_COLOR"] = "1"
        annotator = None
        if args.record_llm or args.replay_llm:
            replay_config = LLMReplayConfig(
                record_path=Path(args.record_llm) if args.record_llm else None,
                replay_path=Path(args.replay_llm) if args.replay_llm else None,
                demo_freeze=args.demo_freeze,
            )
            inner = None if args.replay_llm else OpenAICompatibleLLM()
            annotator = OpenAICompatibleAnnotator(RecordingReplayLLM(inner, replay_config))
        try:
            report = build_skill_library(
                Path(args.repo_path),
                Path(args.output),
                clean=args.clean,
                candidate_mode=args.candidate_mode,
                annotator=annotator,
            )
        except (SkillBuilderError, RuntimeError) as exc:
            print(f"ERROR: {exc}")
            return 1
        print(f"scanned RTL files: {report['rtl_files_scanned']}")
        print(f"modules extracted: {report['modules_extracted']}")
        print(f"skills generated: {report['skills_generated']}")
        print(f"package format: {report['package_format']}")
        print(f"report: {Path(args.output) / 'report.json'}")
        failed = [skill for skill in report["skills"] if skill.get("sim_ok") is False]
        if failed:
            print(f"WARNING: {len(failed)} generated testbench(es) did not pass")
        return 0
    return 1
