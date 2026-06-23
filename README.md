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

The repository includes a small verification-oriented RTL reference library under `skills/`. Each skill is a compact `module_info.json` extracted from open-source RTL design patterns, such as UART TX/RX, FIFO, CDC, I2C, SPI, Wishbone register blocks, ready/valid buffers, and arbitration.

Metadata convention:

- Module/IP skills use `states` for protocol or controller FSM structure.
- Primitive/pattern skills use `behavior + constraints` when an FSM model would be misleading.
- Every skill includes `constraints`, `implementation_notes`, and `verification_goals` so later LLM injection has generation rules and test intent, not just concept labels.
- `source_refs` should point to concrete repository, commit, and file path whenever the source is external.

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
| `axis_fifo` | AXI-stream elastic FIFO with occupancy count | alexforencich/verilog-axis |
| `axis_handshake_buffer` | ready/valid skid or pipeline buffer | alexforencich/verilog-axis |
| `axis_srl_fifo` | shallow AXI-stream SRL/shift-register FIFO | alexforencich/verilog-axis |
| `axis_pipeline_fifo` | AXI-stream register-slice/pipeline FIFO for timing | alexforencich/verilog-axis |
| `round_robin_arbiter` | Fair one-hot request arbiter | alexforencich/verilog-axis |
| `reset_synchronizer` | async assert, sync release reset CDC | alexforencich/verilog-axis |

Build or validate the skill index:

```sh
make skills
python3 -m src.rtl_skill_index --check
```

The generated index is written to `skills/index.json`.

Each skill directory now has this structure:

```text
skills/<skill>/
  module_info.json          machine-readable metadata
  README.md                 LLM-facing usage guide
  template.v                minimal teaching RTL template
  examples/instantiation.v  compact instantiation example
  examples/tb_<skill>.v     self-checking Icarus Verilog testbench
```

Run one skill testbench manually:

```sh
iverilog -g2012 -Wall -o /tmp/uart_tx.vvp \
  skills/uart_tx/template.v \
  skills/uart_tx/examples/tb_uart_tx.v
vvp /tmp/uart_tx.vvp
```

`source_refs` are provenance and learning references only. The local `template.v` files are intentionally small teaching implementations and do not copy external RTL.

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
- Loads matched `module_info.json` files.
- Also searches `skill_spec.json` when present and scores matches against its `retrieval_text`, claims, and unknowns.
- Scores category, interfaces, patterns, ports, parameters, constraints, keywords, and README matches.
- Penalizes `negative_terms`.
- Returns ranked skills with `why_matched`, `penalties`, `risks`, and `adaptation_hints`.

LangChain integration is exposed as a tool named `retrieve_rtl_skills`. The tool accepts the same query-plan fields plus optional `skills_root` and `limit`. It does not call an LLM and does not let the model choose the final skill.

Export local skills to a SkillRouter-compatible JSONL pool:

```sh
python3 -m skill_retriever export-skillrouter-pool \
  --skills-root skills \
  --output /tmp/local_rtl_skillrouter_pool.jsonl
```

Each JSONL record contains `skill_id`, `name`, `description`, `body`, and `source_path`. When `skill_spec.json` exists, the exporter uses its `retrieval_text`, claims, and unknowns; otherwise it falls back to `module_info.json` and `README.md`.

Prepare a single `query_plan.json` for external SkillRouter embedding retrieval without running the model:

```sh
python3 -m skill_retriever prepare-skillrouter-query query_plan.json \
  --skills-root skills \
  --output-dir /tmp/local_rtl_skillrouter_query \
  --tier easy
```

This writes `tasks.jsonl`, `relevance.json`, `manifest.json`, and `easy/part-00000.jsonl`, then prints the external `src.export_retrieval` command to run from `external/SkillRouter/`.

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

The benchmark reports `hit@1`, `mrr@10`, and `recall@5/10/20`. It is a regression seed set for the current curated skills, covering standalone parameter customization, dependency/composite-style retrieval, and similar-skill distinction; it is not a claim of broad router quality.

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

The retriever remains deterministic. The LLM only rewrites the human request into a query plan and generates HDL from the selected skill's `module_info.json`, `README.md`, and `template.v`. Generated HDL must pass `iverilog -g2012 -Wall`; on syntax failure the workflow feeds the compiler log back to the LLM and retries repair up to 3 times before failing.

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

The planner makes a second LLM call to map each LLM-produced submodule onto the current skill taxonomy loaded from `skills/index.json`.

## Automated RTL Skill Builder

The builder converts a local Verilog/SystemVerilog repository into reusable skill packages. The RTL frontend is deterministic: it tries `pyslang` first, falls back to the local regex parser when needed, builds module dependency candidates, and then uses an LLM call only for structured `category`, `interfaces`, `patterns`, and `keywords`.

```sh
python3 -m skill_builder build <repo_path>
```

By default it writes to `./work/built_skills`, which is ignored by git. Use `--output` to choose another directory:

```sh
python3 -m skill_builder build work/sample_rtl_repo --output work/built_skills
```

Candidate selection defaults to compatibility mode, where every extracted module becomes a candidate. Use root-only mode to emit only root candidates:

```sh
python3 -m skill_builder build work/sample_rtl_repo --candidate-mode roots
```

Pipeline:

- Recursively scans for `*.v`, `*.sv`, `*.vh`, and `*.svh`.
- Ignores docs, images, build outputs, simulation outputs, and generated artifacts.
- Extracts module names, parameters, ports, comments, likely FSM states, instances, and common patterns.
- Builds `SkillCandidate` dependency closures from root/internal modules and classifies unresolved dependencies.
- Classifies skills by category, interfaces, keywords, and design patterns through the configured LLM.
- Emits `module_info.json`, LLM-facing `README.md`, educational `template.v`, `manifest.json`, `closure.json`, `quality.json`, `module_ir.json`, `evidence.json`, `skill_spec.json`, `provenance.json`, `adaptation.json`, copied closure sources under `rtl/`, `examples/instantiation.v`, `examples/tb_<module>.v`, and `tests/generated/generated_smoke_tb.v`.
- Creates `tests/original/README.md` to explicitly mark upstream/original tests as not imported yet.
- Writes per-stage tool records under `tool_runs/`: `frontend.json`, `source_compile.json`, `tb_compile.json`, and `simulation.json`.
- Runs staged verification when `iverilog`/`vvp` are available: source-closure compile, generated testbench compile, then smoke simulation.
- Writes `report.json` with frontend, candidate, dependency, staged verification, quality-tier, and legacy per-skill fields.

Try the included local sample:

```sh
make skill-builder-demo
```

Run the external-repo smoke wrapper against a local checkout:

```sh
scripts/build_from_external_repo.sh /path/to/verilog/repo
```

The generated templates are intentionally simplified teaching implementations. They preserve interface shape and basic semantics, but they are not copied from the input project and should not be treated as production replacements.

### Known Limitations

- The frontend uses `pyslang` for syntax acceptance, but metadata extraction still depends on deterministic walkers and regex fallback.
- Builder classification and architecture skill mapping depend on the configured LLM and can vary by provider/model.
- SystemVerilog support is partial and focused on common module headers, parameters, ports, instances, comments, and simple pattern detection.
- Dependency closure quality depends on extracted instance edges; complex generate/package/interface constructs can still produce unresolved dependencies.
- Extracted comments may be incomplete or may miss comments that are far from the module declaration.
- Generated `template.v` files are educational and reproducible, not production-ready replacements for the source RTL.
- `gold_candidate` means generated smoke checks passed; it is not a claim of functional correctness.
- `source_refs` are provenance records only; they are not runtime dependencies and the builder does not download external code.
- `evidence.json` is the first EvidencePack layer. It records deterministic observations such as ports, parameters, instances, clock/reset candidates, comments, FSM hints, and verification stages.
- `skill_spec.json` is generated by a dedicated evidence-aware structured LLM call plus deterministic tool claims. Semantic claims must cite known `evidence_ids`; unknown IDs fail the build instead of being silently accepted. Semantic claims should still be treated as inferred unless separately validated.

## Notes

This is intentionally narrow. It supports small Verilog modules and currently targets UART TX for the HDL-generation demo. The simulator and reporting steps remain separate from the LLM-facing planning/generation layers.
