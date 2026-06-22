from __future__ import annotations

import argparse
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="architecture",
        description="Plan a multi-module RTL architecture from a natural-language hardware requirement.",
    )
    parser.add_argument("requirement", help="Natural-language hardware requirement.")
    parser.add_argument("--output-dir", default="work/architecture", help="Directory for architecture artifacts.")
    args = parser.parse_args(argv)

    from .planner import write_architecture_outputs

    paths = write_architecture_outputs(args.requirement, Path(args.output_dir))
    print(f"architecture_json: {paths['json']}")
    print(f"architecture_md: {paths['markdown']}")
    print(f"architecture_mmd: {paths['mermaid']}")
    print(f"module_specs: {len(paths['specs'])}")
    return 0
