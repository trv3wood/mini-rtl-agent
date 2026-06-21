# mini-rtl-agent Notes

## Current Progress

The repository now has three related flows:

1. A minimal RTL agent demo:
   - Natural language UART TX spec.
   - Deterministic RTL/testbench generation.
   - `iverilog` + `vvp` simulation.
   - Bounded repair loop.
   - Markdown report generation.

2. An RTL Skill Builder:
   - CLI: `python3 -m skill_builder build <repo_path>`.
   - Optional clean rebuild: `--clean`.
   - Deterministic parsing only; no LLM calls.
   - Scans `.v` and `.sv` files.
   - Ignores docs, images, build outputs, generated files, and test outputs.
   - Extracts module names, parameters, ports, nearby comments, simple FSM hints, and common design patterns.
   - Classifies category, interfaces, keywords, and patterns.
   - Generates skill packages:

```text
work/built_skills/<skill_name>/
  module_info.json
  README.md
  template.v
  examples/
    instantiation.v
    tb_<module>.v
```

The manually curated skills now live under `skills/` and are intended to be committed. They are richer and still useful as a reference target for future builder quality improvements.

3. An LLM HDL Agent demo:
   - CLI: `python3 -m hdl_agent "<natural-language HDL request>" --show-trace`.
   - LLM configuration is centralized in `src/utils/llm.py`.
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
  -> agent reads the top skill's module_info.json, README.md, and template.v
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

## Hardening Added

- Regression tests in `tests/test_skill_builder.py`.
- LLM HDL agent tests in `tests/test_hdl_agent.py`.
- Golden-output tests against `work/sample_rtl_repo`.
- Python schema validator in `src/skill_builder/schema.py`.
- Provenance fields in generated `module_info.json`:
  - `source_file`
  - `detected_module_name`
  - `builder_version`
  - `parser_mode: deterministic`
- External repo smoke wrapper:

```sh
scripts/build_from_external_repo.sh <local-repo-path>
```

The wrapper writes to:

```text
work/external_skills/<repo-name>/
```

Generated output paths are ignored by git:

```text
work/generated/
work/built_skills/
work/external_skills/
```

The curated root `skills/` is not ignored, so changes there can be committed.

## Commands Recently Verified

```sh
make skill-builder-demo
PATH=/home/zys/mini-rtl-agent/.venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 pytest -q
scripts/build_from_external_repo.sh work/sample_rtl_repo
python3 -m hdl_agent --help
iverilog -g2012 -Wall -o /tmp/agent_uart.vvp work/generated/agent_rtl.v
```

Latest pytest result:

```text
23 passed
```

Latest real LLM smoke result from the user:

```text
query_plan intent: design a UART transmitter
retrieved top-3: uart_tx, uart_rx, axis_handshake_buffer
selected_skill: uart_tx
wrote: work/generated/agent_rtl.v
```

The generated `work/generated/agent_rtl.v` compiled with `iverilog -g2012 -Wall`.

## External Smoke Results

The builder was run against open-source repositories already cloned under `/tmp`:

```text
/tmp/verilog-uart-provenance
/tmp/verilog-axis-provenance
/tmp/generic-fifos-provenance
/tmp/i2c-provenance
/tmp/spi-provenance
```

Summary:

```text
verilog-uart-provenance: scanned 30, modules 28, skills 28, failed 0
verilog-axis-provenance: scanned 85, modules 31, skills 31, failed 5
generic-fifos-provenance: scanned 8, modules 6, skills 6, failed 6
i2c-provenance: scanned 7, modules 7, skills 7, failed 1
spi-provenance: scanned 8, modules 6, skills 6, failed 1
```

Known failed generated testbenches:

```text
axis_adapter
axis_async_fifo
axis_async_fifo_adapter
axis_fifo_adapter
axis_ram_switch
generic_fifo_dc
generic_fifo_dc_gray
generic_fifo_lfsr
generic_fifo_sc_a
generic_fifo_sc_b
lfsr
wb_master_model
```

These failures are useful signal: the smoke test is exposing the current deterministic template generator boundary rather than hiding it.

## Current Boundaries

- The parser is heuristic and regex/text based. It is not a full Verilog/SystemVerilog frontend.
- SystemVerilog support is partial.
- Non-ANSI and ANSI module headers are covered by tests, but complex generate blocks, interfaces, packages, macros, typedefs, modports, and parameter types remain weak spots.
- Comment extraction is local and may miss design intent far away from the module declaration.
- FSM detection is shallow. It catches common symbolic state names and `case(state)` style patterns, but it is not semantic analysis.
- Pattern classification is keyword based. It can over-classify or miss modules with unusual naming.
- `template.v` preserves interface shape and provides a synthesizable educational stub. It is not a behaviorally equivalent implementation of the source RTL.
- Generated self-checking testbenches prove that the generated template compiles and runs, not that it matches the original module behavior.
- Complex modules such as async FIFOs, AXIS adapters, bus master models, and LFSRs currently need pattern-specific template/testbench generators.
- `source_refs` are provenance and learning references only. The builder does not download or copy upstream RTL into generated templates.
- Query-plan values are still free-form LLM output. The retriever tolerates this through positive-term matching, but interface/category names can drift from the curated skill taxonomy.
- The LLM HDL agent currently performs syntax checking only. It does not yet auto-run the selected skill's self-checking testbench against generated HDL.
- HDL generation is strongly grounded by the selected skill template. This is useful for demo stability, but it means the output may look close to the template unless the request forces customization.
- Real provider calls require a local `.env` or exported `LLM_*` variables. `.env` is ignored by git; `.env.example` is commit-safe.

## Suggested Next Steps

1. Add pattern-specific template generators for:
   - FIFO
   - LFSR
   - AXIS ready/valid adapter
   - async FIFO skeleton
   - Wishbone test helper/model filtering

2. Improve file filtering:
   - Exclude `tb_*`, `*_tb`, `test_*`, and known simulation models by default unless a flag requests them.

3. Split quality scoring into stricter gates:
   - metadata score
   - compile score
   - simulation score
   - pattern-confidence score

4. Add an optional parser backend later:
   - Surelog/UHDM, slang, tree-sitter, or Pyverilog.
   - Keep deterministic regex parser as the zero-dependency fallback.

5. Use curated `skills/` as golden examples for what high-quality generated packages should eventually resemble.

6. Harden the LLM HDL agent:
   - Normalize query-plan category/interface values against the known skill taxonomy.
   - Add optional simulation with the selected skill testbench after syntax passes.
   - Write an agent trace artifact alongside `agent_rtl.v` for reports and demos.
