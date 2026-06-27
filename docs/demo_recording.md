# HDL Agent Demo Recording

This project supports recording and replaying HDL Agent demos with a JSONL LLM cache. Replay mode avoids live network calls and still runs JSON parsing, schema validation, RTL syntax checking, C++ code generation, build, and tests.

## Record A Terminal Session

Create output directories:

```sh
mkdir -p demo/recordings demo/cache
```

Record a terminal session:

```sh
script -q -t 2> demo/recordings/hdl_agent_demo.time demo/recordings/hdl_agent_demo.typescript
```

Inside the recorded shell, run either a live recording command or an offline replay command from the sections below. Exit the shell when done:

```sh
exit
```

Replay the terminal session:

```sh
scriptreplay demo/recordings/hdl_agent_demo.time demo/recordings/hdl_agent_demo.typescript
```

## Generate An LLM Cache

This calls the configured live LLM and records every raw response to JSONL:

Live recording sends the HDL request, selected skill context, generated RTL context, and artifact-generation prompts to the configured external LLM API. Use offline replay for demos when you do not want network calls.

```sh
.venv/bin/python -m hdl_agent \
  "Create IP named custom_priority8 that converts an 8-bit request vector into a valid flag and encoded winning index." \
  --skills-root skills \
  --output-dir work/generated/custom_priority8 \
  --emit-spec \
  --emit-cpp-ref \
  --build-cpp-ref \
  --run-cpp-ref-tests \
  --record-llm demo/cache/custom_priority8.jsonl \
  --demo-freeze \
  --no-color \
  --show-trace
```

The cache records:

- `call_index`
- `call_name`
- `prompt_hash`
- `messages`
- `raw_response`
- `parsed_artifact_type`
- `created_at`

## Offline Replay

Replay forbids live LLM calls. Each current prompt is hashed and compared with the recorded `prompt_hash`; a mismatch fails immediately with `prompt changed`.

```sh
.venv/bin/python -m hdl_agent \
  "Create IP named custom_priority8 that converts an 8-bit request vector into a valid flag and encoded winning index." \
  --skills-root skills \
  --output-dir work/generated/custom_priority8 \
  --emit-spec \
  --emit-cpp-ref \
  --build-cpp-ref \
  --run-cpp-ref-tests \
  --replay-llm demo/cache/custom_priority8.jsonl \
  --demo-freeze \
  --no-color \
  --show-trace
```

## One-Command Demo Script

Live record:

```sh
RECORD_LLM=demo/cache/custom_priority8.jsonl scripts/demo_hdl_agent_artifacts.sh
```

Offline replay:

```sh
REPLAY_LLM=demo/cache/custom_priority8.jsonl scripts/demo_hdl_agent_artifacts.sh
```

The script uses `--demo-freeze` and `--no-color` by default.
