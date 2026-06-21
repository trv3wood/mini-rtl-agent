# wishbone_reg_block

Small Wishbone-compatible register block with address decode, read mux, write strobes, acknowledge, and optional interrupt/status bits.

This skill directory is self-contained for local teaching and simulation. `module_info.json` is the machine-readable index. `template.v` is a clean teaching implementation written for this repository; it is not copied from the external `source_refs`.

## When to use

- Every documented writable register can be written and read back where applicable.
- Read-only status fields reflect hardware inputs and ignore software writes.
- wishbone
- register block
- address decode

Use this skill when the generated RTL needs the behavior described above and the constraints below match the target design.

## When not to use

- One-shot command bits need explicit clear behavior after hardware consumption.
- Read mux must return deterministic values for reserved addresses.

Do not use this skill when the interface, timing model, or clock-domain assumptions differ materially from the template.

## Port semantics

- `clk` (input, 1): Bus clock.
- `rst` (input, 1): Bus reset.
- `wb_adr_i` (input, ADDR_WIDTH): Register address.
- `wb_dat_i` (input, DATA_WIDTH): Write data.
- `wb_dat_o` (output, DATA_WIDTH): Read data.
- `wb_we_i` (input, 1): Write enable.
- `wb_stb_i` (input, 1): Transfer strobe.
- `wb_cyc_i` (input, 1): Valid bus cycle.
- `wb_ack_o` (output, 1): Single-cycle acknowledge.
- `irq_o` (output, 1): Optional interrupt output.

## Parameter semantics

- `ADDR_WIDTH` default `3`: Register address width.
- `DATA_WIDTH` default `8`: Register data width.

## Behavior model

- IDLE: No active bus transaction.
- ACK: Acknowledge the selected register access for one cycle.

## Usage constraints

- Acknowledge each accepted Wishbone transaction exactly according to the selected wait-state policy.
- Writes must not overwrite read-only hardware status fields.
- One-shot command bits need explicit clear behavior after hardware consumption.
- Read mux must return deterministic values for reserved addresses.

## Implementation notes

- Derive a write-access strobe from cyc, stb, we, and the acknowledge policy.
- Use a registered ack pulse to avoid combinational loops into the bus fabric.
- Keep write decode and read mux in separate always/case blocks for reviewability.
- Document reset values for every software-visible register.

## Common errors

- Treating `source_refs` as code dependencies. They are provenance and learning references only.
- Changing handshake or reset polarity without updating the testbench and metadata.
- Reusing the template in a wider production design without reviewing timing, reset, and CDC assumptions.

## Verification checklist

- Every documented writable register can be written and read back where applicable.
- Read-only status fields reflect hardware inputs and ignore software writes.
- ack timing is one pulse per bus access.
- Command and interrupt clear bits have no unintended sticky behavior.

## Files

- `module_info.json`: machine-readable metadata for retrieval and planning.
- `template.v`: minimal teaching RTL template.
- `examples/instantiation.v`: compact instantiation example.
- `examples/tb_wishbone_reg_block.v`: self-checking Icarus Verilog testbench.
