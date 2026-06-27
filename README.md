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

The skill retriever main path is intentionally small:

```text
user query -> LLM-generated query_plan.json -> rg over compact_card.json -> ranked skills with scores and reasons
```

The LLM is used only to rewrite the user request into `query_plan.json`. Final skill ranking is deterministic and comes from local `compact_card.json` files.

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

Generate a query plan with the configured OpenAI-compatible LLM:

```sh
python3 -m skill_retriever plan "design a UART transmitter with ready/valid input and busy output"
```

Run the full user-query retrieval path:

```sh
python3 -m skill_retriever query "design a UART transmitter with ready/valid input and busy output" \
  --skills-root skills \
  --limit 5
```

Run semantic user-query cases that intentionally avoid direct skill keywords:

```sh
.venv/bin/python -m skill_retriever user-benchmark benchmarks/semantic_user_queries.json \
  --skills-root work/built_skills \
  --max-cases 1 \
  --limit 5
```

Use `--max-cases 1` for a cheap real-LLM smoke. Remove it when you are ready to spend one LLM call per case.

Run deterministic retrieval from an existing query plan:

```sh
python3 -m skill_retriever search query_plan.json
python3 -m skill_retriever search query_plan.json --format json
```

The retriever:

- Uses `positive_terms` with `ripgrep`.
- Loads matched `compact_card.json` files from minimal skills.
- Scores compact-card fields: `core_function`, `algorithm`, `structure`, `keywords`, `retrieval_text`, `interface_signature`, and `granularity`.
- Adds evidence from `likely_categories`, `likely_interfaces`, and `required_features`.
- Penalizes `negative_terms`.
- Returns deterministic ranked skills with `why_matched` and `penalties`.

LangChain integration exposes the deterministic retriever as an upstream-agent tool:

- `retrieve_rtl_skills`: returns ranked skill results and preserves the original retriever JSON output.

The tool accepts the same query-plan fields plus optional `skills_root` and `limit`. It does not call an LLM or let the model choose the final skill.

External SkillRouter integration code remains in the repository as an experimental comparison path, but it is not part of the current default retriever workflow.

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

## Automated RTL Skill Builder

The builder converts a local Verilog/SystemVerilog repository into reusable skill packages. The package format is minimal: it writes only `skill.json`, `compact_card.json`, and copied RTL. Structural parsing and candidate filtering are deterministic; semantic annotation uses the shared `src/utils/llm.py` client when `LLM_*` is configured and falls back to local rules otherwise.

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

In minimal mode the builder does not generate README/template/quality/evidence files, and the retriever can search the resulting `compact_card.json` files directly.

Candidate selection defaults to compatibility mode, where every extracted module becomes a candidate. Use root-only mode to emit only root candidates:

```sh
python3 -m skill_builder build work/sample_rtl_repo --candidate-mode roots
```

Pipeline:

- Recursively scans for `*.v`, `*.sv`, `*.vh`, and `*.svh`.
- Ignores docs, images, build outputs, simulation outputs, and generated artifacts.
- Extracts module names, parameters, ports, comments, likely FSM states, instances, and common patterns.
- Builds `SkillCandidate` dependency closures from root/internal modules and classifies unresolved dependencies.
- Applies conservative accepted-skill gates: no duplicate module definitions, self-contained atomic RTL only, at most 500 copied RTL lines, and at most one detected state-machine `case` over a state/fsm signal.
- Writes minimal per-skill packages: `skill.json`, `compact_card.json`, and copied RTL under `rtl/`.
- Writes `report.json` with frontend, candidate, dependency, accepted-skill, and `rejected_candidates` summary fields. Rejected candidates do not stop the batch run.

Try the included local sample:

```sh
make skill-builder-demo
```

External open-source RTL growth uses a staged workflow:

```sh
git clone --depth 1 https://github.com/alexforencich/verilog-axis.git work/external_skills/verilog-axis
git clone --depth 1 https://github.com/alexforencich/verilog-uart.git work/external_skills/verilog-uart
git clone --depth 1 https://github.com/lowRISC/opentitan.git work/external_skills/opentitan
git clone --depth 1 https://github.com/lowRISC/ibex.git work/external_skills/ibex

scripts/smoke_external_skill_repos.sh
```

Raw upstream checkouts stay under ignored `work/external_skills/`; generated packages stay under ignored `work/built_skills/`. Review `work/built_skills/<repo>/report.json` and selected skill directories before promoting anything into commit-ready `skills/`. See `workflow.md` for the full smoke -> batch -> review -> promote policy.

Latest external-library smoke/batch results with the atomic gates:

| Repo | RTL files | Modules | Accepted skills | Rejected candidates |
| --- | ---: | ---: | ---: | ---: |
| `verilog-axis` | 85 | 31 | 20 | 11 |
| `verilog-uart` | 30 | 28 | 2 | 26 |
| `opentitan` primitives | 203 | 121 | 71 | 50 |
| `ibex` | 640 | 209 | 88 | 121 |

### Known Limitations

- The frontend uses `pyslang` for syntax acceptance, but metadata extraction still depends on deterministic walkers and regex fallback.
- Architecture skill mapping depends on the configured LLM and can vary by provider/model.
- SystemVerilog support is partial and focused on common module headers, parameters, ports, instances, comments, and simple pattern detection.
- Dependency closure quality depends on extracted instance edges; complex generate/package/interface constructs can still produce unresolved dependencies.
- Extracted comments may be incomplete or may miss comments that are far from the module declaration.
- The builder does not perform automatic verification in this phase; generated skills should be treated as compact retrieval/RTL packages, not quality-certified IP.
- The "at most one FSM" gate is a lightweight static heuristic over `case(state/fsm...)`, not formal FSM analysis.
- Large external checkouts live under `work/external_skills/`; pytest is configured to collect only this repository's `tests/` so third-party scripts are not imported during local test runs.

## Notes

This is intentionally narrow. It supports small Verilog modules and currently targets UART TX for the HDL-generation demo. The simulator and reporting steps remain separate from the LLM-facing planning/generation layers.
