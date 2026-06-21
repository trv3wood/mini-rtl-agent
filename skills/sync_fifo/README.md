# sync_fifo

Single-clock FIFO with write/read enables, full/empty flags, and optional count tracking.

This skill directory is self-contained for local teaching and simulation. `module_info.json` is the machine-readable index. `template.v` is a clean teaching implementation written for this repository; it is not copied from the external `source_refs`.

## When to use

- No data is lost or reordered across fill, drain, and pointer wrap.
- full asserts at DEPTH entries and blocks extra writes without a simultaneous read.
- fifo
- synchronous
- buffer

Use this skill when the generated RTL needs the behavior described above and the constraints below match the target design.

## When not to use

- Never allow read to advance occupancy below zero.
- Define whether rd_data is first-word fall-through or registered output before generating RTL.

Do not use this skill when the interface, timing model, or clock-domain assumptions differ materially from the template.

## Port semantics

- `clk` (input, 1): Single FIFO clock.
- `rst` (input, 1): Reset pointers and flags.
- `wr_en` (input, 1): Write request.
- `wr_data` (input, DATA_WIDTH): Write payload.
- `rd_en` (input, 1): Read request.
- `rd_data` (output, DATA_WIDTH): Read payload.
- `full` (output, 1): No free entries.
- `empty` (output, 1): No valid entries.
- `count` (output, ADDR_WIDTH+1): Optional occupancy count.

## Parameter semantics

- `DATA_WIDTH` default `8`: Payload width.
- `DEPTH` default `16`: Number of FIFO entries; usually power of two.
- `ADDR_WIDTH` default `4`: Address bits for DEPTH entries.

## Behavior model

- EMPTY: Read pointer equals write pointer and count is zero.
- PARTIAL: Some entries valid; reads and writes may occur simultaneously.
- FULL: Count equals DEPTH; block writes unless read also occurs.

## Usage constraints

- Use only one clock domain; use async_fifo when read and write clocks differ.
- Never allow write to advance occupancy beyond DEPTH.
- Never allow read to advance occupancy below zero.
- Define whether rd_data is first-word fall-through or registered output before generating RTL.

## Implementation notes

- Use circular read/write pointers and a count register or extra pointer bit to distinguish full from empty.
- Handle simultaneous read and write as a separate case so occupancy remains correct.
- Infer memory with a reg array unless the target flow requires an explicit RAM macro.
- Register full/empty flags when timing is more important than zero-cycle flag updates.

## Common errors

- Treating `source_refs` as code dependencies. They are provenance and learning references only.
- Changing handshake or reset polarity without updating the testbench and metadata.
- Reusing the template in a wider production design without reviewing timing, reset, and CDC assumptions.

## Verification checklist

- No data is lost or reordered across fill, drain, and pointer wrap.
- full asserts at DEPTH entries and blocks extra writes without a simultaneous read.
- empty asserts at zero entries and blocks extra reads without a simultaneous write.
- Simultaneous read/write keeps occupancy stable when FIFO is neither full nor empty.

## Files

- `module_info.json`: machine-readable metadata for retrieval and planning.
- `template.v`: minimal teaching RTL template.
- `examples/instantiation.v`: compact instantiation example.
- `examples/tb_sync_fifo.v`: self-checking Icarus Verilog testbench.
