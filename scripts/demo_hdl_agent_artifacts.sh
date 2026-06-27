#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON:-.venv/bin/python}"
OUTPUT_DIR="${OUTPUT_DIR:-work/generated/custom_priority8}"
REQUEST="${REQUEST:-Create IP named custom_priority8 that converts an 8-bit request vector into a valid flag and encoded winning index.}"

log() {
  printf '[demo] %s\n' "$*"
}

die() {
  printf '[demo] ERROR: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

if [ ! -x "$PYTHON_BIN" ]; then
  die "Python executable not found: $PYTHON_BIN. Set PYTHON=/path/to/python or create .venv."
fi

require_cmd iverilog
if ! command -v g++ >/dev/null 2>&1 && ! command -v clang++ >/dev/null 2>&1; then
  die "missing required C++ compiler: install g++ or clang++"
fi

log "checking LLM configuration"
"$PYTHON_BIN" - <<'PY'
from src.utils.llm import LLMConfig

try:
    config = LLMConfig.from_env()
except RuntimeError as exc:
    raise SystemExit(
        f"{exc}\n"
        "Create .env from .env.example or export LLM_API_KEY, LLM_BASE_URL, LLM_MODEL."
    )

print(f"[demo] LLM_BASE_URL={config.base_url}")
print(f"[demo] LLM_MODEL={config.model}")
PY

log "cleaning output dir: $OUTPUT_DIR"
rm -rf "$OUTPUT_DIR"

log "running HDL agent artifact flow"
"$PYTHON_BIN" -m hdl_agent \
  "$REQUEST" \
  --skills-root skills \
  --output-dir "$OUTPUT_DIR" \
  --emit-spec \
  --emit-cpp-ref \
  --build-cpp-ref \
  --run-cpp-ref-tests \
  --show-trace

log "checking expected artifacts"
for rel in \
  query_plan.json \
  retrieval_trace.json \
  final_ip_context.json \
  engineer_spec.json \
  cpp_model.json \
  reports/iverilog_check.json \
  reports/cpp_build.json \
  reports/cpp_test.json
do
  [ -f "$OUTPUT_DIR/$rel" ] || die "missing artifact: $OUTPUT_DIR/$rel"
done

RTL_PATH="$("$PYTHON_BIN" - <<'PY' "$OUTPUT_DIR/final_ip_context.json"
import json
import sys
from pathlib import Path

context = json.loads(Path(sys.argv[1]).read_text())
print(context["final_rtl"]["path"])
PY
)"

[ -f "$RTL_PATH" ] || die "missing RTL from final_ip_context: $RTL_PATH"

IP_NAME="$("$PYTHON_BIN" - <<'PY' "$OUTPUT_DIR/final_ip_context.json"
import json
import sys
from pathlib import Path

context = json.loads(Path(sys.argv[1]).read_text())
print(context["final_rtl"]["module_name"])
PY
)"

for rel in \
  "cpp/${IP_NAME}_ref.h" \
  "cpp/${IP_NAME}_ref.cpp" \
  "cpp/test_${IP_NAME}_ref.cpp" \
  cpp/CMakeLists.txt
do
  [ -f "$OUTPUT_DIR/$rel" ] || die "missing C++ artifact: $OUTPUT_DIR/$rel"
done

log "checking report status"
"$PYTHON_BIN" - <<'PY' "$OUTPUT_DIR"
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
for rel in ["reports/iverilog_check.json", "reports/cpp_build.json", "reports/cpp_test.json"]:
    report = json.loads((root / rel).read_text())
    status = report.get("status")
    print(f"[demo] {rel}: {status}")
    if status != "passed":
        raise SystemExit(f"{rel} did not pass: {json.dumps(report, indent=2)}")

spec = json.loads((root / "engineer_spec.json").read_text())
model = json.loads((root / "cpp_model.json").read_text())
print(f"[demo] spec ip_name={spec['ip_name']} source_skill={spec['source_skill']}")
print(f"[demo] cpp model kind={model['model_kind']} function={model['function_signature']['name']}")
PY

log "done"
log "artifacts: $OUTPUT_DIR"
