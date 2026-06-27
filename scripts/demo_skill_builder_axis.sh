#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
INPUT_REPO="${INPUT_REPO:-work/built_skills/verilog-axis}"
OUTPUT_DIR="${OUTPUT_DIR:-work/generated/skill_builder_axis}"
RECORD_LLM="${RECORD_LLM:-}"
REPLAY_LLM="${REPLAY_LLM:-}"
CANDIDATE_MODE="${CANDIDATE_MODE:-all}"

if [ -n "$RECORD_LLM" ] && [ -n "$REPLAY_LLM" ]; then
  echo "ERROR: set only one of RECORD_LLM or REPLAY_LLM" >&2
  exit 2
fi

if [ ! -d "$INPUT_REPO" ]; then
  echo "ERROR: input repo not found: $INPUT_REPO" >&2
  exit 2
fi

echo "[demo-skill-builder] input: $INPUT_REPO"
echo "[demo-skill-builder] output: $OUTPUT_DIR"
echo "[demo-skill-builder] candidate_mode: $CANDIDATE_MODE"

llm_args=(--demo-freeze --no-color)
if [ -n "$RECORD_LLM" ]; then
  echo "[demo-skill-builder] recording LLM calls: $RECORD_LLM"
  mkdir -p "$(dirname "$RECORD_LLM")"
  : > "$RECORD_LLM"
  llm_args+=(--record-llm "$RECORD_LLM")
elif [ -n "$REPLAY_LLM" ]; then
  if [ ! -f "$REPLAY_LLM" ]; then
    echo "ERROR: replay cache not found: $REPLAY_LLM" >&2
    exit 2
  fi
  echo "[demo-skill-builder] replaying LLM calls: $REPLAY_LLM"
  llm_args+=(--replay-llm "$REPLAY_LLM")
else
  echo "[demo-skill-builder] using live LLM without recording"
fi

echo "[demo-skill-builder] running skill_builder"
"$PYTHON_BIN" -m skill_builder build "$INPUT_REPO" \
  --output "$OUTPUT_DIR" \
  --clean \
  --candidate-mode "$CANDIDATE_MODE" \
  "${llm_args[@]}"

echo "[demo-skill-builder] validating generated skills"
"$PYTHON_BIN" -m src.skill_builder.validate_minimal_skills "$OUTPUT_DIR"

echo "[demo-skill-builder] report summary"
"$PYTHON_BIN" - "$OUTPUT_DIR/report.json" <<'PY'
import json
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text())
semantic = report.get("semantic", {})
print(f"skills_generated={report.get('skills_generated')}")
print(f"skills_rejected={report.get('skills_rejected')}")
print(f"semantic_backend={semantic.get('backend')}")
print(f"llm_used={semantic.get('llm_used')}")
print(f"fallback_count={semantic.get('fallback_count')}")
print("skills=" + ",".join(skill.get("skill_name", "") for skill in report.get("skills", [])))
PY

echo "[demo-skill-builder] done"
