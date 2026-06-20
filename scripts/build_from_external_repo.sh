#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <local-verilog-repo-path>" >&2
  exit 2
fi

repo_path="$1"
repo_name="$(basename "$repo_path")"
output_dir="work/external_skills/$repo_name"

python3 -m skill_builder build "$repo_path" --output "$output_dir" --clean
