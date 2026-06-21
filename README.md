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
| `axis_handshake_buffer` | ready/valid skid or pipeline buffer | alexforencich/verilog-axis |
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
- Scores category, interfaces, patterns, ports, parameters, constraints, keywords, and README matches.
- Penalizes `negative_terms`.
- Returns ranked skills with `why_matched` and `penalties`.

LangChain integration is exposed as a tool named `retrieve_rtl_skills`. The tool accepts the same query-plan fields plus optional `skills_root` and `limit`. It does not call an LLM and does not let the model choose the final skill.

## LLM HDL Agent Demo

The HDL agent demo connects a real OpenAI-compatible LLM endpoint. LLM configuration is centralized in `src/utils/llm.py`; workflow code does not read API keys directly and does not assume a specific provider.

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

The Phase 2 architecture planner uses the configured LLM to decompose system-level hardware requirements into submodules, dependencies, Markdown specs, and Mermaid diagrams. The planner is not limited to a fixed set of local examples; code-side validation keeps the JSON schema and artifact generation testable.

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

Code still annotates each LLM-produced submodule with a likely skill category such as `fifo`, `fsm`, `uart`, `arbiter`, `synchronizer`, `rom`, `multiplier`, or `dsp`.

## Automated RTL Skill Builder

The deterministic builder converts a local Verilog/SystemVerilog repository into reusable skill packages without LLM calls:

```sh
python3 -m skill_builder build <repo_path>
```

By default it writes to `./work/built_skills`, which is ignored by git. Use `--output` to choose another directory:

```sh
python3 -m skill_builder build work/sample_rtl_repo --output work/built_skills
```

Pipeline:

- Recursively scans for `*.v` and `*.sv`.
- Ignores docs, images, build outputs, simulation outputs, and generated artifacts.
- Extracts module names, parameters, ports, comments, likely FSM states, and common patterns.
- Classifies skills by category, interfaces, keywords, and design patterns.
- Emits `module_info.json`, LLM-facing `README.md`, educational `template.v`, `examples/instantiation.v`, and `examples/tb_<module>.v`.
- Runs generated testbenches with `iverilog -g2012` and `vvp` when available.
- Writes `report.json` with per-skill quality scores across metadata, interface, documentation, verification, and template usability.

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

- The parser is heuristic and regex/text based; it is not a full Verilog/SystemVerilog front end.
- SystemVerilog support is partial and focused on common module headers, parameters, ports, comments, and simple pattern detection.
- Extracted comments may be incomplete or may miss comments that are far from the module declaration.
- Generated `template.v` files are educational and reproducible, not production-ready replacements for the source RTL.
- `source_refs` are provenance records only; they are not runtime dependencies and the builder does not download external code.

## Notes

This is intentionally narrow. It supports small Verilog modules and currently targets UART TX. The code is structured so a real LLM backend can replace the deterministic generator later without changing the simulator or reporting steps.
