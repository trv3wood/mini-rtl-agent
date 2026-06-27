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
   - Default output is the minimal package format. Semantic annotation uses the shared LLM client when `LLM_*` is configured and falls back to local rules otherwise.
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

4. A compact-card skill retriever:
   - Main CLI commands:
     - `python3 -m skill_retriever plan "<user query>"`
     - `python3 -m skill_retriever query "<user query>" --skills-root skills`
     - `python3 -m skill_retriever search query_plan.json --skills-root skills`
   - The current main path is:

```text
user query
  -> LLM-generated query_plan.json
  -> rg over compact_card.json
  -> deterministic compact-card scoring
  -> selected/ranked skills with score, why_matched, and penalties
```

The retriever no longer reads README/module_info/template files on the main path. It scores current `compact_card.json` fields: `core_function`, `algorithm`, `structure`, `keywords`, `retrieval_text`, `interface_signature`, and `granularity`, with additional evidence from query-plan categories/interfaces/features.

External SkillRouter adapter code remains in the repository as an experimental comparison path, but SkillRouter models are not part of the current default workflow.

The retriever now has a seed benchmark CLI:

```sh
python3 -m skill_retriever benchmark benchmarks/router_benchmark.json \
  --skills-root skills \
  --limit 10
```

Latest seed benchmark result:

```text
cases: 14
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
python3 -m skill_retriever search /tmp/query_plan_uart.json --skills-root skills --limit 3
python3 -m skill_retriever benchmark benchmarks/router_benchmark.json --skills-root skills --limit 10
.venv/bin/python -m skill_retriever query "design a UART transmitter with ready valid input and busy output" --skills-root skills --limit 3 --format json
scripts/smoke_external_skill_repos.sh verilog-uart
python3 -m hdl_agent --help
iverilog -g2012 -Wall -o /tmp/agent_uart.vvp work/generated/agent_rtl.v
```

Latest pytest result:

```text
90 passed
```

Latest compact router benchmark:

```text
hit@1=1.000
avg_text_length=38.9
keyword_match_rate=1.000
json_size_reduction=76.0%
retrieval_text_avg_reduction=95.8%
```

Latest real LLM skill retriever smoke result:

```text
user query: design a UART transmitter with ready valid input and busy output
query_plan intent: UART transmitter design with ready-valid input and busy output
retrieved top-3: uart_tx(score=103), uart_rx(score=69), axis_srl_fifo(score=58)
selected top skill: uart_tx
```

Latest real LLM HDL agent smoke result from the user:

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
