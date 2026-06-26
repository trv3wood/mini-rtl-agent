#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON:-python3}"
EXTERNAL_ROOT="${EXTERNAL_ROOT:-work/external_skills}"
SMOKE_ROOT="${SMOKE_ROOT:-work/generated/external_skill_smoke}"
BUILT_ROOT="${BUILT_ROOT:-work/built_skills}"

repos=("$@")
if [ "${#repos[@]}" -eq 0 ]; then
  repos=(verilog-axis verilog-uart opentitan ibex)
fi

repo_files() {
  case "$1" in
    verilog-axis)
      printf '%s\n' \
        rtl/arbiter.v \
        rtl/priority_encoder.v \
        rtl/axis_register.v \
        rtl/axis_fifo.v
      ;;
    verilog-uart)
      printf '%s\n' \
        rtl/uart_tx.v \
        rtl/uart_rx.v
      ;;
    opentitan)
      printf '%s\n' \
        hw/ip/prim_generic/rtl/prim_flop_2sync.sv \
        hw/ip/prim/rtl/prim_pulse_sync.sv \
        hw/ip/prim/rtl/prim_lfsr.sv
      ;;
    ibex)
      printf '%s\n' \
        rtl/ibex_counter.sv \
        rtl/ibex_csr.sv
      ;;
    *)
      echo "unknown repo key: $1" >&2
      return 2
      ;;
  esac
}

batch_repo_path() {
  case "$1" in
    verilog-uart)
      printf '%s\n' "$EXTERNAL_ROOT/$1/rtl"
      ;;
    opentitan)
      printf '%s\n' "$SMOKE_ROOT/$1-batch"
      ;;
    *)
      printf '%s\n' "$EXTERNAL_ROOT/$1"
      ;;
  esac
}

copy_batch_repo() {
  local repo="$1"
  case "$repo" in
    opentitan)
      local src="$EXTERNAL_ROOT/$repo"
      local dst="$SMOKE_ROOT/$repo-batch"
      rm -rf "$dst"
      mkdir -p "$dst"
      for rel in hw/ip/prim/rtl hw/ip/prim_generic/rtl; do
        if [ -d "$src/$rel" ]; then
          mkdir -p "$dst/$rel"
          find "$src/$rel" -maxdepth 1 -type f \( -name '*.v' -o -name '*.sv' -o -name '*.vh' -o -name '*.svh' \) -exec cp {} "$dst/$rel/" \;
        fi
      done
      ;;
    *)
      ;;
  esac
}

copy_smoke_repo() {
  local repo="$1"
  local src="$EXTERNAL_ROOT/$repo"
  local dst="$SMOKE_ROOT/$repo"

  if [ ! -d "$src" ]; then
    echo "missing $src" >&2
    echo "place the local checkout under $src before running smoke tests" >&2
    return 3
  fi

  rm -rf "$dst"
  mkdir -p "$dst"

  local missing=0
  while IFS= read -r rel; do
    if [ -f "$src/$rel" ]; then
      mkdir -p "$dst/$(dirname "$rel")"
      cp "$src/$rel" "$dst/$rel"
    else
      echo "missing smoke file for $repo: $rel" >&2
      missing=1
    fi
  done < <(repo_files "$repo")

  if [ "$missing" -ne 0 ]; then
    return 4
  fi
}

build_and_validate() {
  local input_repo="$1"
  local output_dir="$2"

  "$PYTHON_BIN" -m skill_builder build "$input_repo" --output "$output_dir" --clean
  if find "$output_dir" -mindepth 1 -maxdepth 1 -type d | grep -q .; then
    "$PYTHON_BIN" -m src.skill_builder.validate_minimal_skills "$output_dir"
  else
    echo "no accepted skills to validate: $output_dir"
  fi
}

for repo in "${repos[@]}"; do
  echo "==> smoke: $repo"
  copy_smoke_repo "$repo"
  build_and_validate "$SMOKE_ROOT/$repo" "$BUILT_ROOT/smoke/$repo"

  echo "==> batch: $repo"
  copy_batch_repo "$repo"
  build_and_validate "$(batch_repo_path "$repo")" "$BUILT_ROOT/$repo"
done
