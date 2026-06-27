#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CACHE_PATH="${CACHE_PATH:-demo/cache/custom_priority8.jsonl}"
OUTPUT_DIR="${OUTPUT_DIR:-work/generated/custom_priority8}"

if [ ! -f "$CACHE_PATH" ]; then
  echo "[demo] ERROR: missing LLM replay cache: $CACHE_PATH" >&2
  echo "[demo] Generate it first with:" >&2
  echo "[demo]   RECORD_LLM=$CACHE_PATH scripts/demo_hdl_agent_artifacts.sh" >&2
  exit 1
fi

echo "[demo] offline replay cache: $CACHE_PATH"
echo "[demo] output dir: $OUTPUT_DIR"

REPLAY_LLM="$CACHE_PATH" OUTPUT_DIR="$OUTPUT_DIR" scripts/demo_hdl_agent_artifacts.sh
