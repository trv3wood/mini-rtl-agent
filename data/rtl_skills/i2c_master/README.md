# i2c_master

I2C master controller with software-visible command/status registers and open-drain SCL/SDA controls.

This skill directory is self-contained for local teaching and simulation. `module_info.json` is the machine-readable index. `template.v` is a clean teaching implementation written for this repository; it is not copied from the external `source_refs`.

## When to use

- Wishbone writes update prescale/control/command registers at the documented addresses.
- A write transaction produces start, address/data bits, ACK sample, and stop in order.
- i2c
- master
- wishbone

Use this skill when the generated RTL needs the behavior described above and the constraints below match the target design.

## When not to use

- Expose arbitration-lost status when sampled bus state conflicts with the master drive intent.
- Clear one-shot command bits when the byte controller acknowledges completion.

Do not use this skill when the interface, timing model, or clock-domain assumptions differ materially from the template.

## Port semantics

- `wb_clk_i` (input, 1): Wishbone clock.
- `wb_rst_i` (input, 1): Wishbone synchronous reset.
- `arst_i` (input, 1): Asynchronous reset.
- `wb_adr_i` (input, 3): Register address.
- `wb_dat_i` (input, 8): Wishbone write data.
- `wb_dat_o` (output, 8): Wishbone read data.
- `wb_we_i` (input, 1): Write enable.
- `wb_stb_i` (input, 1): Strobe.
- `wb_cyc_i` (input, 1): Bus cycle valid.
- `wb_ack_o` (output, 1): Bus acknowledge.
- `wb_inta_o` (output, 1): Interrupt output.
- `scl_pad_i` (input, 1): SCL pad input.
- `scl_pad_o` (output, 1): SCL pad output value, normally 0 for open-drain drive.
- `scl_padoen_o` (output, 1): SCL output enable, active low.
- `sda_pad_i` (input, 1): SDA pad input.
- `sda_pad_o` (output, 1): SDA pad output value, normally 0 for open-drain drive.
- `sda_padoen_o` (output, 1): SDA output enable, active low.

## Parameter semantics

- `ARST_LVL` default `1'b1`: Asynchronous reset active level.
- `DEFAULT_SLAVE_ADDR` default `7'b1111110`: Optional default slave address register value.

## Behavior model

- IDLE: Bus is free, waiting for command register start/read/write bits.
- START: Generate SDA falling edge while SCL high.
- BIT_TRANSFER: Shift address/data bits and sample ACK.
- ACK: Handle acknowledge bit in either master read or write direction.
- STOP: Release SDA high while SCL high.
- ARBITRATION_LOST: Detected mismatch on open-drain bus while trying to drive.

## Usage constraints

- SCL and SDA are open-drain style signals: drive low or release, never actively drive high.
- Preserve start and stop timing relative to SCL high periods.
- Expose arbitration-lost status when sampled bus state conflicts with the master drive intent.
- Clear one-shot command bits when the byte controller acknowledges completion.

## Implementation notes

- Keep register decode, byte controller, and bit controller as separate conceptual blocks.
- Use prescale registers to derive SCL timing enables from the bus clock.
- Represent command register bits for start, stop, read, write, ack, and interrupt acknowledge.
- Latch status bits for rxack, bus busy, arbitration lost, transfer in progress, and interrupt pending.

## Common errors

- Treating `source_refs` as code dependencies. They are provenance and learning references only.
- Changing handshake or reset polarity without updating the testbench and metadata.
- Reusing the template in a wider production design without reviewing timing, reset, and CDC assumptions.

## Verification checklist

- Wishbone writes update prescale/control/command registers at the documented addresses.
- A write transaction produces start, address/data bits, ACK sample, and stop in order.
- SDA changes only when allowed by the I2C phase except for start/stop conditions.
- Arbitration lost and NACK cases are observable through status bits.

## Files

- `module_info.json`: machine-readable metadata for retrieval and planning.
- `template.v`: minimal teaching RTL template.
- `examples/instantiation.v`: compact instantiation example.
- `examples/tb_i2c_master.v`: self-checking Icarus Verilog testbench.
