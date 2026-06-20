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

## Run

```sh
make demo
```

Or pass your own short spec:

```sh
python3 -m src.agent --spec "UART transmitter, 8 data bits, LSB first, start/done/busy, one stop bit"
```

Useful demo flag:

```sh
python3 -m src.agent --inject-bug
```

That intentionally creates a first bad RTL attempt so the repair loop has something to fix.

## Outputs

- Generated RTL: `work/generated/uart_tx.v`
- Generated testbench: `work/generated/tb_uart_tx.v`
- Simulator binary/logs: `work/generated/`
- Report: `work/reports/report.md`

## Project Layout

```text
src/                  Python implementation
data/rtl_skills/      Structured RTL design pattern skills
work/generated/       Generated RTL, testbench, and simulation artifacts
work/reports/         Markdown report
```

## RTL Skill Library

The repository includes a small verification-oriented RTL reference library under `data/rtl_skills/`. Each skill is a compact `module_info.json` extracted from open-source RTL design patterns, such as UART TX/RX, FIFO, CDC, I2C, SPI, Wishbone register blocks, ready/valid buffers, and arbitration.

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

The generated index is written to `data/rtl_skills/index.json`.

Each skill directory now has this structure:

```text
data/rtl_skills/<skill>/
  module_info.json          machine-readable metadata
  README.md                 LLM-facing usage guide
  template.v                minimal teaching RTL template
  examples/instantiation.v  compact instantiation example
  examples/tb_<skill>.v     self-checking Icarus Verilog testbench
```

Run one skill testbench manually:

```sh
iverilog -g2012 -Wall -o /tmp/uart_tx.vvp \
  data/rtl_skills/uart_tx/template.v \
  data/rtl_skills/uart_tx/examples/tb_uart_tx.v
vvp /tmp/uart_tx.vvp
```

`source_refs` are provenance and learning references only. The local `template.v` files are intentionally small teaching implementations and do not copy external RTL.

## Notes

This is intentionally narrow. It supports small Verilog modules and currently targets UART TX. The code is structured so a real LLM backend can replace the deterministic generator later without changing the simulator or reporting steps.
