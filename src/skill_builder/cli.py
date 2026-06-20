from __future__ import annotations

import argparse
from pathlib import Path

from .builder import SkillBuilderError, build_skill_library


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="skill_builder", description="Build RTL skills from a Verilog repository.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Build a skill library from a repository.")
    build_parser.add_argument("repo_path", help="Path to a repository containing Verilog/SystemVerilog RTL.")
    build_parser.add_argument(
        "--output",
        default="skills",
        help="Output directory for generated skills. Defaults to ./skills.",
    )
    build_parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove previously generated skill directories in the output before rebuilding.",
    )

    args = parser.parse_args(argv)
    if args.command == "build":
        try:
            report = build_skill_library(Path(args.repo_path), Path(args.output), clean=args.clean)
        except SkillBuilderError as exc:
            print(f"ERROR: {exc}")
            return 1
        print(f"scanned RTL files: {report['rtl_files_scanned']}")
        print(f"modules extracted: {report['modules_extracted']}")
        print(f"skills generated: {report['skills_generated']}")
        print(f"report: {Path(args.output) / 'report.json'}")
        failed = [skill for skill in report["skills"] if not skill["sim_ok"]]
        if failed:
            print(f"WARNING: {len(failed)} generated testbench(es) did not pass")
        return 0
    return 1
