# async_fifo

Dual-clock FIFO for crossing data between independent write and read clock domains.

This skill directory is self-contained for local teaching and simulation. `module_info.json` is the machine-readable index. `template.v` is a clean teaching implementation written for this repository; it is not copied from the external `source_refs`.

## When to use

- Read sequence exactly matches write sequence under unrelated clock periods.
- wr_full prevents overflow even around pointer wrap.
- async fifo
- cdc
- gray code

Use this skill when the generated RTL needs the behavior described above and the constraints below match the target design.

## When not to use

- Compute full only in the write clock domain and empty only in the read clock domain.
- Do not pass binary counters directly across clock domains.

Do not use this skill when the interface, timing model, or clock-domain assumptions differ materially from the template.

## Port semantics

- `wr_clk` (input, 1): Write clock domain.
- `wr_rst` (input, 1): Write-domain reset.
- `wr_en` (input, 1): Write request in wr_clk domain.
- `wr_data` (input, DATA_WIDTH): Write payload.
- `wr_full` (output, 1): Write domain sees FIFO full.
- `rd_clk` (input, 1): Read clock domain.
- `rd_rst` (input, 1): Read-domain reset.
- `rd_en` (input, 1): Read request in rd_clk domain.
- `rd_data` (output, DATA_WIDTH): Read payload.
- `rd_empty` (output, 1): Read domain sees FIFO empty.

## Parameter semantics

- `DATA_WIDTH` default `8`: Payload width.
- `ADDR_WIDTH` default `4`: Address bits; FIFO depth is 2**ADDR_WIDTH.

## Behavior model

- WRITE_SPACE: Write pointer is not one full lap ahead of synchronized read pointer.
- WRITE_FULL: Next write Gray pointer equals inverted-MSB synchronized read pointer.
- READ_DATA: Read pointer differs from synchronized write pointer.
- READ_EMPTY: Read pointer equals synchronized write pointer.

## Usage constraints

- Use Gray-coded pointers for multi-bit cross-domain pointer transfer.
- Synchronize write pointer into the read domain and read pointer into the write domain with multi-stage synchronizers.
- Compute full only in the write clock domain and empty only in the read clock domain.
- Do not pass binary counters directly across clock domains.

## Implementation notes

- Maintain local binary pointers for RAM addressing and convert the next pointer value to Gray code for CDC.
- Full detection compares the next write Gray pointer against the synchronized read Gray pointer with inverted top bits.
- Empty detection compares the next read Gray pointer against the synchronized write Gray pointer.
- Use separate reset synchronization for each clock domain if resets are asynchronous.

## Common errors

- Treating `source_refs` as code dependencies. They are provenance and learning references only.
- Changing handshake or reset polarity without updating the testbench and metadata.
- Reusing the template in a wider production design without reviewing timing, reset, and CDC assumptions.

## Verification checklist

- Read sequence exactly matches write sequence under unrelated clock periods.
- wr_full prevents overflow even around pointer wrap.
- rd_empty prevents underflow even around pointer wrap.
- No combinational path crosses between wr_clk and rd_clk domains.

## Files

- `module_info.json`: machine-readable metadata for retrieval and planning.
- `template.v`: minimal teaching RTL template.
- `examples/instantiation.v`: compact instantiation example.
- `examples/tb_async_fifo.v`: self-checking Icarus Verilog testbench.
