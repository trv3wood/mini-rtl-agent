# mini-rtl-agent

A minimal Python RTL agent demo for a small EDA workflow:

Natural language spec -> retrieve reference Verilog -> generate RTL -> generate testbench -> run `iverilog`/`vvp` -> feed failures back into a repair loop -> write final Verilog and a Markdown report.

The first supported target is a small UART transmitter. There is no LangChain, vector database, or external service dependency in the default demo. The generator is deterministic so the project can run locally and fail early when tools are missing.

## Requirements

- Python 3.10+
- `iverilog` and `vvp` on `PATH`

Check:

```sh
iverilog -V
vvp -V
```

## Project Layout

```text
src/                  Python implementation
skills/               Structured RTL design pattern skills
work/generated/       Generated RTL, testbench, and simulation artifacts
work/reports/         Markdown report
```

## RTL Skill Library

The repository includes a small compact RTL reference library under `skills/`. Each skill is intentionally minimal: a deterministic retrieval card, a structured skill JSON file, and one RTL source file.

Current skills:

| Skill | Pattern | Reference family |
| --- | --- | --- |
| `uart_tx` | UART transmit FSM with baud/prescale timing | alexforencich/verilog-uart, local demo ref |
| `uart_rx` | UART receive sampler with frame/overrun errors | alexforencich/verilog-uart |
| `sync_fifo` | Single-clock circular FIFO | freecores/generic_fifos, alexforencich/verilog-axis |
| `async_fifo` | Dual-clock Gray-pointer FIFO | freecores/generic_fifos, alexforencich/verilog-axis |
| `i2c_master` | Wishbone-controlled I2C master | OpenCores I2C |
| `spi_master` | Configurable SPI master shifter | OpenCores SPI |
| `wishbone_reg_block` | Control/status register wrapper | OpenCores I2C/SPI style |
| `axis_adapter` | AXI-stream data width adapter | alexforencich/verilog-axis |
| `axis_fifo` | AXI-stream elastic FIFO with occupancy count | alexforencich/verilog-axis |
| `axis_handshake_buffer` | ready/valid skid or pipeline buffer | alexforencich/verilog-axis |
| `axis_srl_fifo` | shallow AXI-stream SRL/shift-register FIFO | alexforencich/verilog-axis |
| `axis_pipeline_fifo` | AXI-stream register-slice/pipeline FIFO for timing | alexforencich/verilog-axis |
| `round_robin_arbiter` | Fair one-hot request arbiter | alexforencich/verilog-axis |
| `reset_synchronizer` | async assert, sync release reset CDC | alexforencich/verilog-axis |

Validate the committed minimal skill library:

```sh
make skills
```

Each skill directory now has this structure:

```text
skills/<skill>/
  skill.json          minimal structured skill metadata
  compact_card.json   router-facing retrieval card
  rtl/<skill>.v       RTL source used by the downstream agent
```

Run one skill RTL syntax check manually:

```sh
iverilog -g2012 -Wall -o /tmp/uart_tx.vvp \
  skills/uart_tx/rtl/uart_tx.v
```

`compact_card.json` is the only file used by the deterministic retriever. `skill.json` points to the RTL files consumed after routing.

## Skill Retriever

The skill retriever is designed for an LLM agent workflow. The LLM agent rewrites a natural-language request into `query_plan.json`; this repository only performs deterministic retrieval and ranking from that plan.

Example `query_plan.json`:

```json
{
  "intent": "fair arbiter with acknowledge",
  "positive_terms": ["fair", "arbiter", "grant", "request", "acknowledge"],
  "negative_terms": [],
  "likely_categories": ["control"],
  "likely_interfaces": ["arbiter"],
  "required_features": ["acknowledge", "round_robin"]
}
```

Run the retriever:

```sh
python3 -m skill_retriever search query_plan.json
python3 -m skill_retriever search query_plan.json --format json
```

The retriever:

- Uses `positive_terms` with `ripgrep`.
- Loads matched `compact_card.json` files from minimal skills.
- Scores compact retrieval text plus structured fields derived from `skill.json`: interfaces, structure, parameters, keywords, and RTL paths.
- Penalizes `negative_terms`.
- Returns deterministic ranked skills with `why_matched` and `penalties`; optional external fusion keeps the same result shape.

LangChain integration exposes deterministic tools for an upstream LLM agent:

- `retrieve_rtl_skills`: returns ranked skill results and preserves the original retriever JSON output.
- `route_rtl_skill`: returns the downstream-agent contract with `selected_skill`, `candidate_skills`, matched capabilities, required adaptations, risks, and `source_path`.

Both tools accept the same query-plan fields plus optional `skills_root` and `limit`. `route_rtl_skill` also accepts optional `external_json` and `task_id` to route over fused external SkillRouter results. Neither tool calls an LLM or lets the model choose the final skill.

Return a downstream-agent router response with `selected_skill`, `candidate_skills`, matched capabilities, adaptations, risks, and source path:

```sh
python3 -m skill_retriever route query_plan.json \
  --skills-root skills
```

If external SkillRouter retrieval/rerank output is available, route over the fused ranking:

```sh
python3 -m skill_retriever route query_plan.json \
  --skills-root skills \
  --external-json external/SkillRouter/outputs/local_rtl_query/reranked/easy.json
```

Export local skills to a SkillRouter-compatible JSONL pool:

```sh
python3 -m skill_retriever export-skillrouter-pool \
  --skills-root skills \
  --output /tmp/local_rtl_skillrouter_pool.jsonl
```

Each JSONL record contains `skill_id`, `name`, `description`, `body`, and `source_path`. Skills are exported from `compact_card.json` plus `skill.json`.

Prepare a single `query_plan.json` for external SkillRouter embedding retrieval without running the model:

```sh
python3 -m skill_retriever prepare-skillrouter-query query_plan.json \
  --skills-root skills \
  --output-dir /tmp/local_rtl_skillrouter_query \
  --tier easy
```

This writes `tasks.jsonl`, `relevance.json`, `manifest.json`, and `easy/part-00000.jsonl`, then prints the external `src.export_retrieval` command to run from `external/SkillRouter/`.

Use the optional adapter to prepare data and print the exact external command without launching the model:

```sh
python3 -m skill_retriever run-skillrouter-query query_plan.json \
  --skills-root skills \
  --external-root external/SkillRouter \
  --work-dir work/skillrouter_query \
  --dry-run
```

When you are ready to run the external embedding model, remove `--dry-run`. The adapter invokes `external/SkillRouter/src.export_retrieval`, reads `outputs/local_rtl_query/retrieval/easy.json`, and fuses those semantic hits with the local lexical/spec-aware ranking.

To also run the released reranker on the retrieved local candidates, use:

```sh
python3 -m skill_retriever run-skillrouter-query query_plan.json \
  --skills-root skills \
  --external-root external/SkillRouter \
  --work-dir work/skillrouter_query \
  --mode pipeline
```

Pipeline mode runs embedding retrieval first, then invokes `scripts/skillrouter_rerank_query.py` with the external SkillRouter virtualenv. This is separate from the external project's `src.run_open_model_eval` benchmark entrypoint, which expects gold labels.

If you run the printed external command manually, import and fuse the existing output without launching models again:

```sh
python3 -m skill_retriever run-skillrouter-query query_plan.json \
  --skills-root skills \
  --external-root external/SkillRouter \
  --work-dir work/skillrouter_query \
  --mode pipeline \
  --use-existing \
  --format json
```

For report-friendly comparison between local lexical/spec-aware retrieval, raw external SkillRouter order, and fused ranking:

```sh
python3 -m skill_retriever compare-skillrouter-query query_plan.json \
  --skills-root skills \
  --external-json external/SkillRouter/outputs/local_rtl_query/reranked/easy.json
```

For benchmark-level comparison, use an external retrieval/reranked JSON whose task IDs match the benchmark case IDs:

```sh
make router-benchmark
make skillrouter-benchmark-dry-run

# run the printed external commands manually from external/SkillRouter

make skillrouter-report-existing
make skillrouter-status
```

The `make` targets are intentionally split so model execution stays explicit. Override paths as needed:

```sh
make skillrouter-report-existing \
  SKILLROUTER_EXTERNAL_JSON=external/SkillRouter/outputs/local_rtl_benchmark/reranked/easy.json
```

The underlying command is:

```sh
python3 -m skill_retriever run-skillrouter-benchmark benchmarks/router_benchmark.json \
  --skills-root skills \
  --external-root external/SkillRouter \
  --work-dir work/skillrouter_benchmark \
  --mode pipeline \
  --dry-run

# remove --dry-run to let the adapter launch external retrieval/rerank,
# or run the printed commands manually and then use --use-existing

python3 -m skill_retriever run-skillrouter-benchmark benchmarks/router_benchmark.json \
  --skills-root skills \
  --external-root external/SkillRouter \
  --work-dir work/skillrouter_benchmark \
  --mode pipeline \
  --use-existing \
  --report-md work/reports/skillrouter_benchmark.md \
  --report-json work/reports/skillrouter_benchmark.json \
  --format json
```

The lower-level manual path is:

```sh
python3 -m skill_retriever prepare-skillrouter-benchmark benchmarks/router_benchmark.json \
  --skills-root skills \
  --output-dir /tmp/local_rtl_skillrouter_benchmark

# then run the printed external src.export_retrieval command from external/SkillRouter

python3 -m skill_retriever compare-skillrouter-benchmark benchmarks/router_benchmark.json \
  --skills-root skills \
  --external-json external/SkillRouter/outputs/local_rtl_benchmark/reranked/easy.json \
  --report-md work/reports/skillrouter_benchmark.md \
  --format json
```

This reports local, raw external, semantic-scored, and fused `hit@1`, `mrr@10`, and `recall@5/10/20`.
Generated report files under `work/reports/` are ignored by git.
`make skillrouter-status` writes a GOAL.md alignment report that lists implemented router capabilities, boundaries, and next steps.

After external SkillRouter writes `outputs/local_rtl_query/retrieval/easy.json`, fuse that semantic result with the local lexical/spec-aware retriever:

```sh
python3 -m skill_retriever fuse-skillrouter-results query_plan.json \
  --skills-root skills \
  --retrieval-json external/SkillRouter/outputs/local_rtl_query/retrieval/easy.json \
  --task-id local_query \
  --format json
```

The fused JSON contains `lexical_results`, `semantic_results`, and final `results`. Semantic hits include `external SkillRouter rank ...` in `why_matched`.

Run the small seed router benchmark:

```sh
python3 -m skill_retriever benchmark benchmarks/router_benchmark.json \
  --skills-root skills \
  --limit 10
```

The benchmark reports `hit@1`, `mrr@10`, `recall@5/10/20`, `avg_text_length`, and `keyword_match_rate`. It is a regression seed set for the current curated skills, covering standalone parameter customization, dependency/composite-style retrieval, and similar-skill distinction; it is not a claim of broad router quality.

## LLM HDL Agent Demo

The HDL agent demo connects a real OpenAI-compatible LLM endpoint. LLM configuration is centralized in `src/utils/llm.py`; workflow code does not read API keys directly and does not assume a specific provider.
Structured LLM outputs use LangChain's `PydanticOutputParser` in `src/utils/llm.py`.

Create a local `.env` from the example, or export the same variables in your shell:

```sh
cp .env.example .env
```

`.env` is loaded automatically by `src/utils/llm.py` and is ignored by git.

```sh
LLM_API_KEY=...
LLM_BASE_URL=https://api.example.com/v1
LLM_MODEL=provider-model-name
LLM_TIMEOUT_SECONDS=60
```

Run natural language -> query plan -> skill retriever tool -> selected skill context -> generated HDL -> `iverilog` syntax check:

```sh
python3 -m hdl_agent "Create a small UART transmitter with ready/valid input and busy output" --show-trace
```

Default output:

```text
work/generated/agent_rtl.v
```

The retriever remains deterministic. The LLM only rewrites the human request into a query plan and generates HDL from the selected skill's `skill.json`, `compact_card.json`, and RTL source. Generated HDL must pass `iverilog -g2012 -Wall`; on syntax failure the workflow feeds the compiler log back to the LLM and retries repair up to 3 times before failing.

## Architecture Planner

The Phase 2 architecture planner uses the configured LLM to decompose system-level hardware requirements into submodules, dependencies, Markdown specs, and Mermaid diagrams. The planner is not limited to a fixed set of local examples; structured output parsing and validation go through LangChain/Pydantic schemas while artifact generation remains testable.

Run:

```sh
python3 -m architecture "Design a UART receiver with FIFO buffering"
make architecture-demo
```

Default outputs:

```text
work/architecture/architecture.json
work/architecture/architecture.md
work/architecture/architecture.mmd
work/architecture/specs/<submodule>.md
```

The output schema is:

```json
{
  "top_module": "...",
  "submodules": [],
  "connections": [],
  "notes": []
}
```

The planner makes a second LLM call to map each LLM-produced submodule onto the current compact skill library.

## Automated RTL Skill Builder

The builder converts a local Verilog/SystemVerilog repository into reusable skill packages. The default package format is minimal and does not call an LLM: it parses module structure deterministically, copies RTL, and writes only `skill.json` and `compact_card.json`.

```sh
python3 -m skill_builder build <repo_path>
```

By default it writes to `./work/built_skills`, which is ignored by git. Use `--output` to choose another directory:

```sh
python3 -m skill_builder build work/sample_rtl_repo --output work/built_skills
```

The default compact package path writes only `skill.json`, `compact_card.json`, and copied RTL files:

```sh
python3 -m skill_builder build work/sample_rtl_repo \
  --output work/built_skills \
  --clean

make skill-builder-demo
```

In minimal mode the builder does not call an LLM, does not generate README/template/quality/evidence files, and the retriever can search the resulting `compact_card.json` files directly.

Candidate selection defaults to compatibility mode, where every extracted module becomes a candidate. Use root-only mode to emit only root candidates:

```sh
python3 -m skill_builder build work/sample_rtl_repo --candidate-mode roots
```

Pipeline:

- Recursively scans for `*.v`, `*.sv`, `*.vh`, and `*.svh`.
- Ignores docs, images, build outputs, simulation outputs, and generated artifacts.
- Extracts module names, parameters, ports, comments, likely FSM states, instances, and common patterns.
- Builds `SkillCandidate` dependency closures from root/internal modules and classifies unresolved dependencies.
- Writes minimal per-skill packages: `skill.json`, `compact_card.json`, and copied RTL under `rtl/`.
- Writes `report.json` with frontend, candidate, dependency, and package summary fields.

Try the included local sample:

```sh
make skill-builder-demo
```

Run the external-repo smoke wrapper against a local checkout:

```sh
scripts/build_from_external_repo.sh /path/to/verilog/repo
```

The minimal builder copies RTL sources into each skill package.

### Known Limitations

- The frontend uses `pyslang` for syntax acceptance, but metadata extraction still depends on deterministic walkers and regex fallback.
- Architecture skill mapping depends on the configured LLM and can vary by provider/model.
- SystemVerilog support is partial and focused on common module headers, parameters, ports, instances, comments, and simple pattern detection.
- Dependency closure quality depends on extracted instance edges; complex generate/package/interface constructs can still produce unresolved dependencies.
- Extracted comments may be incomplete or may miss comments that are far from the module declaration.
- The builder does not perform automatic verification in this phase; generated skills should be treated as compact retrieval/RTL packages, not quality-certified IP.

## Notes

This is intentionally narrow. It supports small Verilog modules and currently targets UART TX for the HDL-generation demo. The simulator and reporting steps remain separate from the LLM-facing planning/generation layers.
