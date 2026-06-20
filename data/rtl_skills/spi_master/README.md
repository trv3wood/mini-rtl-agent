# spi_master

SPI master that shifts words over MOSI/MISO with configurable clock polarity, phase, divider, and chip select.

This skill directory is self-contained for local teaching and simulation. `module_info.json` is the machine-readable index. `template.v` is a clean teaching implementation written for this repository; it is not copied from the external `source_refs`.

## When to use

- Loopback MOSI to MISO returns the transmitted word.
- All four CPOL/CPHA modes produce expected launch/sample edge ordering.
- spi
- master
- mosi

Use this skill when the generated RTL needs the behavior described above and the constraints below match the target design.

## When not to use

- Chip select must cover the complete transfer word unless continuous/burst mode is explicitly implemented.
- Avoid using internally generated SCLK as a fabric clock when a clock-enable strobe is sufficient.

Do not use this skill when the interface, timing model, or clock-domain assumptions differ materially from the template.

## Port semantics

- `clk` (input, 1): System clock.
- `rst` (input, 1): Reset.
- `start` (input, 1): Begin transfer.
- `tx_data` (input, DATA_WIDTH): Data to shift out.
- `rx_data` (output, DATA_WIDTH): Data shifted in.
- `busy` (output, 1): Transfer active.
- `done` (output, 1): One-cycle transfer complete pulse.
- `sclk` (output, 1): SPI serial clock.
- `mosi` (output, 1): Master-out serial bit.
- `miso` (input, 1): Master-in serial bit.
- `cs_n` (output, CS_WIDTH): Active-low chip select.

## Parameter semantics

- `DATA_WIDTH` default `8`: Transfer word width.
- `CS_WIDTH` default `1`: Number of chip-select outputs.
- `DIV_WIDTH` default `16`: Clock divider width.

## Behavior model

- IDLE: SCLK at idle polarity, chip select inactive.
- ASSERT_CS: Select target before first clock edge.
- TRANSFER: Toggle SCLK, shift MOSI, sample MISO according to CPOL/CPHA.
- DEASSERT_CS: Finish word and release chip select.

## Usage constraints

- SCLK idle value must match CPOL.
- Launch and sample edges must match CPHA for the selected mode.
- Chip select must cover the complete transfer word unless continuous/burst mode is explicitly implemented.
- Avoid using internally generated SCLK as a fabric clock when a clock-enable strobe is sufficient.

## Implementation notes

- Use a divider counter to generate SCLK edge enables from clk.
- Keep TX and RX shift registers plus a bit counter sized for DATA_WIDTH.
- Separate edge phase logic from shift register update logic to keep CPOL/CPHA clear.
- Pulse done after the final sample edge and deassert busy when chip select can be released.

## Common errors

- Treating `source_refs` as code dependencies. They are provenance and learning references only.
- Changing handshake or reset polarity without updating the testbench and metadata.
- Reusing the template in a wider production design without reviewing timing, reset, and CDC assumptions.

## Verification checklist

- Loopback MOSI to MISO returns the transmitted word.
- All four CPOL/CPHA modes produce expected launch/sample edge ordering.
- cs_n is asserted before the first active edge and released after the final edge.
- done pulses once per completed word.

## Files

- `module_info.json`: machine-readable metadata for retrieval and planning.
- `template.v`: minimal teaching RTL template.
- `examples/instantiation.v`: compact instantiation example.
- `examples/tb_spi_master.v`: self-checking Icarus Verilog testbench.
