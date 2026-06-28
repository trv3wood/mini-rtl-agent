#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
SKILLS_ROOT="${SKILLS_ROOT:-skills}"
EXTERNAL_ROOT="${EXTERNAL_ROOT:-external/SkillRouter}"
WORK_DIR="${WORK_DIR:-work/skillrouter_demo}"
OUTPUT_DIR="${OUTPUT_DIR:-outputs/local_rtl_query_demo}"
QUERY_PLAN="${QUERY_PLAN:-$WORK_DIR/query_plan.json}"
LIMIT="${LIMIT:-8}"
TOP_K="${TOP_K:-20}"
MODE="${MODE:-pipeline}"
TIER="${TIER:-easy}"
DRY_RUN="${DRY_RUN:-0}"
ENCODER_BATCH_SIZE="${ENCODER_BATCH_SIZE:-16}"
RERANKER_BATCH_SIZE="${RERANKER_BATCH_SIZE:-4}"
ENCODER_MAX_LENGTH="${ENCODER_MAX_LENGTH:-1024}"
RERANKER_MAX_LENGTH="${RERANKER_MAX_LENGTH:-1024}"
ENCODER_MODEL="${ENCODER_MODEL:-pipizhao/SkillRouter-Embedding-0.6B}"
RERANKER_MODEL="${RERANKER_MODEL:-pipizhao/SkillRouter-Reranker-0.6B}"

export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"

log() {
  printf '[demo-skill-retriever] %s\n' "$*"
}

die() {
  printf '[demo-skill-retriever] ERROR: %s\n' "$*" >&2
  exit 1
}

[ -x "$PYTHON_BIN" ] || die "Python executable not found: $PYTHON_BIN"
[ -d "$SKILLS_ROOT" ] || die "skills root not found: $SKILLS_ROOT"
[ -d "$EXTERNAL_ROOT" ] || die "external SkillRouter checkout not found: $EXTERNAL_ROOT"

mkdir -p "$WORK_DIR"

cat > "$QUERY_PLAN" <<'JSON'
{
  "intent": "Design a priority encoder for an 8-bit request vector that reports whether any request is active and returns the encoded index of the winning request.",
  "positive_terms": [
    "priority encoder",
    "8-bit request",
    "valid flag",
    "encoded index",
    "combinational"
  ],
  "negative_terms": [
    "fifo",
    "uart",
    "serial"
  ],
  "likely_categories": [
    "encoder",
    "priority",
    "combinational"
  ],
  "likely_interfaces": [
    "request_vector",
    "valid_output",
    "encoded_output"
  ],
  "required_features": [
    "priority encoding",
    "valid flag",
    "binary encoded index"
  ]
}
JSON

log "query_plan: $QUERY_PLAN"
log "skills_root: $SKILLS_ROOT"
log "external_root: $EXTERNAL_ROOT"
log "work_dir: $WORK_DIR"
log "output_dir: $OUTPUT_DIR"
log "mode: $MODE"
log "tier: $TIER"
log "limit: $LIMIT top_k: $TOP_K"
log "encoder_model: $ENCODER_MODEL"
log "reranker_model: $RERANKER_MODEL"
log "PYTORCH_CUDA_ALLOC_CONF=$PYTORCH_CUDA_ALLOC_CONF"

cmd=(
  "$PYTHON_BIN" -m skill_retriever search "$QUERY_PLAN"
  --skills-root "$SKILLS_ROOT"
  --backend skillrouter
  --skillrouter-mode "$MODE"
  --external-root "$EXTERNAL_ROOT"
  --work-dir "$WORK_DIR/data_root"
  --output-dir "$OUTPUT_DIR"
  --tier "$TIER"
  --limit "$LIMIT"
  --top-k "$TOP_K"
  --encoder-model "$ENCODER_MODEL"
  --reranker-model "$RERANKER_MODEL"
  --encoder-max-length "$ENCODER_MAX_LENGTH"
  --reranker-max-length "$RERANKER_MAX_LENGTH"
  --encoder-batch-size "$ENCODER_BATCH_SIZE"
  --reranker-batch-size "$RERANKER_BATCH_SIZE"
)

if [ "$DRY_RUN" = "1" ]; then
  cmd+=(--dry-run --format json)
fi

log "running:"
printf '  %q' "${cmd[@]}"
printf '\n'

"${cmd[@]}"

log "done"
log "query_plan: $QUERY_PLAN"
log "prepared data_root: $WORK_DIR/data_root"
log "external outputs are under: $EXTERNAL_ROOT/$OUTPUT_DIR"
