# mini-rtl-agent Notes

## Current Progress

The repository now has four related flows:

1. A minimal RTL agent demo:
   - Natural language UART TX spec.
   - Deterministic RTL/testbench generation.
   - `iverilog` + `vvp` simulation.
   - Bounded repair loop.
   - Markdown report generation.

2. An RTL Skill Builder:
   - CLI: `python3 -m skill_builder build <repo_path>`.
   - Optional clean rebuild: `--clean`.
   - Deterministic RTL frontend with `pyslang` first and regex fallback.
   - Module hierarchy/root/unresolved-dependency reporting.
   - Default output is the new minimal package format; no LLM call is needed for the default builder path.
   - Scans `.v`, `.sv`, `.vh`, and `.svh` files.
   - Ignores docs, images, build outputs, generated files, and test outputs.
   - Extracts module names, parameters, ports, nearby comments, simple FSM hints, and common design patterns.
   - Generates skill packages:

```text
work/built_skills/<skill_name>/
  skill.json
  compact_card.json
  rtl/
```

   - `skill.json` holds the compact structured metadata and RTL paths.
   - `compact_card.json` is the only retrieval input. It keeps `retrieval_text <= 60` words, `keywords <= 10`, and `structure <= 4`.

The manually curated skills now live under `skills/` in minimal form and are intended to be committed.

3. An LLM HDL Agent demo:
   - CLI: `python3 -m hdl_agent "<natural-language HDL request>" --show-trace`.
   - LLM configuration is centralized in `src/utils/llm.py`.
   - Structured LLM outputs use LangChain `PydanticOutputParser` with Pydantic schemas.
   - `.env` is loaded through `python-dotenv`; `.env.example` documents the provider-neutral variables:
     - `LLM_API_KEY`
     - `LLM_BASE_URL`
     - `LLM_MODEL`
     - `LLM_TIMEOUT_SECONDS`
   - The workflow is:

```text
human HDL request
  -> LLM rewrites request into query_plan.json
  -> LangChain-registered retrieve_rtl_skills tool ranks skills deterministically
  -> agent reads the top skill's skill.json, compact_card.json, and RTL source
  -> LLM generates HDL
  -> iverilog -g2012 -Wall syntax check
  -> on syntax failure, compiler log + broken HDL are fed back for repair
  -> fail after 3 repair attempts
```

Default generated output:

```text
work/generated/agent_rtl.v
```

The retriever remains deterministic. The LLM is used for query-plan rewriting, HDL generation, and syntax-error repair only; it does not directly choose the final skill outside the ranked retriever result.

The local deterministic retriever is now compact-card based:

```text
query_plan.json
  -> rg over compact_card.json
  -> score compact_card plus selected skill.json fields
  -> return ranked skills with why_matched, penalties, risks, and adaptation_hints
```

The retriever no longer reads README/module_info/template files on the main path.

It can also export local skills to the JSONL pool format expected by the external SkillRouter project:

```sh
python3 -m skill_retriever export-skillrouter-pool \
  --skills-root skills \
  --output /tmp/local_rtl_skillrouter_pool.jsonl
```

Current curated export smoke:

```text
skills/ -> /tmp/local_rtl_skillrouter_pool.jsonl
records: 14
fields: skill_id, name, description, body, source_path
```

It can prepare a local query data root for external SkillRouter embedding retrieval without launching the model:

```sh
python3 -m skill_retriever prepare-skillrouter-query query_plan.json \
  --skills-root skills \
  --output-dir /tmp/local_rtl_skillrouter_query \
  --tier easy
```

Latest local query prep smoke:

```text
query: UART transmitter with ready/valid and busy
data_root: /tmp/local_rtl_skillrouter_query
tasks: tasks.jsonl with task_id uart_tx_query
pool: easy/part-00000.jsonl with 14 local skills
external command printed: .venv/bin/python -m src.export_retrieval ...
```

It now also has an optional external SkillRouter adapter:

```sh
python3 -m skill_retriever run-skillrouter-query query_plan.json \
  --skills-root skills \
  --external-root external/SkillRouter \
  --work-dir work/skillrouter_query \
  --dry-run
```

Current adapter behavior:

```text
dry-run: prepares local SkillRouter data_root and prints the exact external command
route: returns the GOAL.md-style downstream Agent contract with selected_skill, candidate_skills, adaptations, risks, and source_path
route_rtl_skill LangChain tool: exposes that same contract to an upstream LLM agent, optionally over fused external SkillRouter JSON
retrieval mode: runs external/SkillRouter/src.export_retrieval, imports retrieval/<tier>.json, fuses with local ranking
pipeline mode: runs retrieval first, then scripts/skillrouter_rerank_query.py for unlabeled local reranker inference, imports reranked/<tier>.json, and fuses with local ranking
use-existing: skips model execution and imports the expected retrieval/<tier>.json or reranked/<tier>.json after a manual run
compare-skillrouter-query: compares local top-k, raw external top-k, semantic-scored top-k, and fused top-k for report tables
compare-skillrouter-benchmark: compares local, raw external, semantic-scored, and fused metrics when external task IDs match benchmark case IDs
run-skillrouter-benchmark: prepares benchmark data, optionally runs external retrieval/rerank, and returns comparison metrics
```

External retrieval output can now be imported and fused with the local retriever:

```sh
python3 -m skill_retriever fuse-skillrouter-results query_plan.json \
  --skills-root skills \
  --retrieval-json external/SkillRouter/outputs/local_rtl_query/retrieval/easy.json \
  --task-id local_query \
  --format json
```

Fusion output contains:

```text
lexical_results: local deterministic/spec-aware ranking
semantic_results: external SkillRouter retrieval JSON mapped back to local skills
results: fused ranking with external rank evidence in why_matched
```

Latest fusion smoke used a synthetic external retrieval JSON:

```text
external ranks: uart_tx, axis_handshake_buffer, uart_rx
fused top-1: uart_tx
why_matched includes: external SkillRouter rank 1: uart_tx
```

Benchmark-level comparison is now available for report tables:

```sh
make router-benchmark
make skillrouter-benchmark-dry-run

# run the printed external commands manually from external/SkillRouter

make skillrouter-report-existing
make skillrouter-status
```

Underlying commands:

```sh
python3 -m skill_retriever run-skillrouter-benchmark benchmarks/router_benchmark.json \
  --skills-root skills \
  --external-root external/SkillRouter \
  --work-dir work/skillrouter_benchmark \
  --mode pipeline \
  --dry-run

python3 -m skill_retriever run-skillrouter-benchmark benchmarks/router_benchmark.json \
  --skills-root skills \
  --external-root external/SkillRouter \
  --work-dir work/skillrouter_benchmark \
  --mode pipeline \
  --use-existing \
  --report-md work/reports/skillrouter_benchmark.md \
  --report-json work/reports/skillrouter_benchmark.json \
  --format json

python3 -m skill_retriever prepare-skillrouter-benchmark benchmarks/router_benchmark.json \
  --skills-root skills \
  --output-dir /tmp/local_rtl_skillrouter_benchmark

python3 -m skill_retriever compare-skillrouter-benchmark benchmarks/router_benchmark.json \
  --skills-root skills \
  --external-json external/SkillRouter/outputs/local_rtl_benchmark/reranked/easy.json \
  --format json
```

It reports local, raw external, semantic-scored, and fused `hit@1`, `mrr@10`, and `recall@5/10/20`. The external JSON must map each benchmark case ID to a ranked skill-id list.
`work/reports/` is gitignored because these are generated comparison artifacts.
`make skillrouter-status` writes the current GOAL.md Skill Router alignment report, including explicit boundaries and next steps.

The retriever now has a seed benchmark CLI:

```sh
python3 -m skill_retriever benchmark benchmarks/router_benchmark.json \
  --skills-root skills \
  --limit 10
```

Latest seed benchmark result:

```text
cases: 12
hit@1: 1.000
mrr@10: 1.000
recall@5/10/20: 1.000
covered intents: UART TX, sync FIFO, async FIFO CDC, round-robin arbiter, ready/valid skid buffer,
standalone FIFO parameter customization, async FIFO dependency/composite retrieval,
UART RX vs TX distinction, SPI vs I2C distinction,
AXI-stream FIFO vs SRL FIFO vs pipeline FIFO distinction
```

This is a regression seed set for the current curated library, not a broad router quality claim.

Curated AXIS streaming skills now include a small similar-family set:

```text
axis_fifo: elastic AXI-stream FIFO for burst buffering and occupancy/count tracking
axis_adapter: AXI-stream width conversion without storage semantics
axis_srl_fifo: shallow SRL/shift-register FIFO for small LUT-style stream buffering
axis_pipeline_fifo: register-slice/pipeline FIFO for timing closure and controlled latency
axis_handshake_buffer: one-word skid/simple ready-valid boundary
```

`make skills` validates all 14 curated minimal skills and checks that only `skill.json`, `compact_card.json`, and `rtl/` are present in each skill directory.

## Hardening Added

- Regression tests in `tests/test_skill_builder.py`.
- Minimal package regression checks validate `skill.json`, `compact_card.json`, RTL paths, compact text length, and keyword limits.
- Retriever tests cover compact-card retrieval text participation in recall/scoring and no-README retrieval.
- LLM HDL agent tests in `tests/test_hdl_agent.py`.
- Golden-output tests against `work/sample_rtl_repo`.
- External repo staging workflow:

```sh
scripts/smoke_external_skill_repos.sh
```

The workflow uses ignored staging roots:

```text
work/external_skills/<repo-name>/  # local upstream checkouts
work/built_skills/<repo-name>/     # generated packages for review
```

Generated output paths are ignored by git:

```text
work/generated/
work/built_skills/
work/external_skills/
```

The curated root `skills/` is not ignored, so changes there can be committed.

Accepted-skill gates now enforce the current project policy:

- no duplicate module definitions
- self-contained atomic candidates only: no dependency closure modules and no unresolved dependencies
- copied RTL is at most 500 lines
- at most one detected state-machine `case` over a state/fsm signal
- rejected candidates are recorded under `report.json -> rejected_candidates` and do not stop batch parsing

Latest external RTL smoke/batch result:

```text
verilog-axis: 85 files, 31 modules, 20 accepted, 11 rejected
verilog-uart: 30 files, 28 modules, 2 accepted, 26 rejected
opentitan primitives: 203 files, 121 modules, 71 accepted, 50 rejected
ibex: 640 files, 209 modules, 88 accepted, 121 rejected
```

The `verilog-uart` batch now keeps only `uart_rx` and `uart_tx`; repeated board-example wrappers are rejected instead of stopping the run. OpenTitan is scoped to primitive RTL rather than the full SoC tree. `workflow.md` records the smoke -> batch -> review -> promote process.

## Commands Recently Verified

```sh
make skill-builder-demo
PATH=/home/zys/mini-rtl-agent/.venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 pytest -q
scripts/smoke_external_skill_repos.sh verilog-uart
python3 -m hdl_agent --help
iverilog -g2012 -Wall -o /tmp/agent_uart.vvp work/generated/agent_rtl.v
```

Latest pytest result:

```text
88 passed
```

Latest compact router benchmark:

```text
hit@1=1.000
avg_text_length=38.9
keyword_match_rate=1.000
json_size_reduction=76.0%
retrieval_text_avg_reduction=95.8%
```

Latest real LLM smoke result from the user:

```text
query_plan intent: design a UART transmitter
retrieved top-3: uart_tx, uart_rx, axis_handshake_buffer
selected_skill: uart_tx
wrote: work/generated/agent_rtl.v
```

The generated `work/generated/agent_rtl.v` compiled with `iverilog -g2012 -Wall`.

## External SkillRouter Baseline

The paper project under `external/SkillRouter/` was set up following its README Quick Start:

```text
external/SkillRouter/.venv
data/eval_core/easy/*.jsonl.gz: 10/10 shards
data/eval_core/hard/*.jsonl.gz: 10/10 shards
models: pipizhao/SkillRouter-Embedding-0.6B and pipizhao/SkillRouter-Reranker-0.6B cached by Hugging Face
GPU smoke: RTX 4060 Laptop GPU, torch.cuda.is_available() = true outside the sandbox
```

Default README settings OOM on the 8GB GPU. With `encoder_max_length=1024`, `reranker_max_length=1024`, and reduced batches, full Easy and Hard tiers completed:

```text
Easy output: external/SkillRouter/outputs/open_model_eval_easy_8gb/summary.json
  retrieval Hit@1 0.5867, nDCG@10 0.5324, MRR@10 0.6471
  pipeline  Hit@1 0.6533, nDCG@10 0.5675, MRR@10 0.7079

Hard output: external/SkillRouter/outputs/open_model_eval_hard_8gb_b4/summary.json
  retrieval Hit@1 0.5067, nDCG@10 0.4851, MRR@10 0.5922
  pipeline  Hit@1 0.6133, nDCG@10 0.5332, MRR@10 0.6715
```

This is enough evidence for the report-level claim that SkillRouter's reranker improves ranking quality but has materially higher runtime and deployment cost than the current deterministic retriever.

## Current Boundaries

- The frontend uses `pyslang` for syntax acceptance when available, then deterministic walkers/regex fallback to populate `ModuleIR`.
- SystemVerilog extraction is still partial even when `pyslang` accepts the syntax.
- Non-ANSI and ANSI module headers are covered by tests, but complex generate blocks, interfaces, packages, macros, typedefs, modports, and parameter types remain weak spots for metadata extraction.
- Dependency closure currently depends on deterministically extracted instances; missed or false-positive instance extraction directly affects candidate quality.
- Comment extraction is local and may miss design intent far away from the module declaration.
- FSM detection is shallow. It catches common symbolic state names and `case(state)` style patterns, but it is not semantic analysis.
- The atomic quality gate's "at most one FSM" check is a lightweight static heuristic over `case(state/fsm...)`, not formal FSM analysis.
- The builder no longer performs automatic verification or emits EvidencePack/Skill Spec/provenance artifacts in this phase.
- Default minimal packages copy RTL as flat files under `rtl/`; generated teaching templates and self-checking testbenches are out of scope for this phase.
- Batch skill building is conservative: duplicate, composite, unresolved, too-large, or multi-FSM candidates are skipped and reported rather than emitted.
- Query-plan values are still free-form LLM output. The retriever tolerates this through positive-term matching, but interface/category names can drift from the curated skill taxonomy.
- The current router benchmark is intentionally tiny and curated. It now covers 14 seed cases, including axis_adapter width conversion and an AXIS FIFO/SRL FIFO/pipeline FIFO distinction set, but it still does not prove generalization to hundreds of skills.
- The LLM HDL agent currently performs syntax checking only. It does not yet auto-run the selected skill's self-checking testbench against generated HDL.
- HDL generation is strongly grounded by the selected skill template. This is useful for demo stability, but it means the output may look close to the template unless the request forces customization.
- Real provider calls require a local `.env` or exported `LLM_*` variables. `.env` is ignored by git; `.env.example` is commit-safe. Skill-builder semantic annotation shares `src/utils/llm.py` with the HDL agent and falls back to local rules when LLM configuration is missing.
- External SkillRouter has been validated as an optional semantic retrieval/rerank baseline. The local side can now export SkillRouter-compatible JSONL pools, prepare a one-query external retrieval data root, call the external embedding retrieval entrypoint when explicitly requested, run an unlabeled local reranker helper over retrieved candidates, and fuse external retrieval/reranked JSON back into local ranking.
- Pytest is configured to collect only repository tests under `tests/`, so ignored upstream checkouts under `work/external_skills/` are not imported.

## Suggested Next Steps

1. Extend the optional external SkillRouter adapter:
   - run a real local reranker smoke on one query when GPU time is acceptable
   - keep long model runs user-triggered rather than hidden inside the default demo
2. Add optional, separate verification outside the skill package format if report needs compile/smoke evidence.
3. Add pattern-specific template generators for:
   - FIFO
   - LFSR
   - AXIS ready/valid adapter
   - async FIFO skeleton
   - Wishbone test helper/model filtering

4. Improve external-library curation:
   - add repo-specific include/exclude profiles instead of encoding all smoke roots in a shell script
   - add pattern-confidence scoring before promotion to `skills/`
   - add original-test import when upstream tests are discoverable

5. Deepen the `pyslang` frontend:
   - Extract ports, parameters, packages, typedefs, interfaces, and instances from syntax/AST nodes instead of regex walkers.
   - Keep deterministic regex parser as the fallback path for unsupported or malformed files.

6. Use curated `skills/` as golden examples for what high-quality generated packages should eventually resemble.

6. Harden the LLM HDL agent:
   - Normalize query-plan category/interface values against the known skill taxonomy.
   - Add optional simulation with the selected skill testbench after syntax passes.
   - Write an agent trace artifact alongside `agent_rtl.v` for reports and demos.
