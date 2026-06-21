# uart_tx

UART transmitter that accepts a byte or stream word and emits start, data, and stop bits on a serial tx line.

This skill directory is self-contained for local teaching and simulation. `module_info.json` is the machine-readable index. `template.v` is a clean teaching implementation written for this repository; it is not copied from the external `source_refs`.

## When to use

- txd is high during reset and idle.
- A transmitted frame contains one low start bit, DATA_WIDTH LSB-first data bits, and one high stop bit.
- uart
- tx
- transmitter

Use this skill when the generated RTL needs the behavior described above and the constraints below match the target design.

## When not to use

- Data bits are transmitted LSB first unless the spec explicitly requests another order.
- Do not change txd faster than the configured bit period.

Do not use this skill when the interface, timing model, or clock-domain assumptions differ materially from the template.

## Port semantics

- `clk` (input, 1): System clock.
- `rst` (input, 1): Synchronous reset.
- `s_axis_tdata` (input, DATA_WIDTH): Transmit payload byte/word.
- `s_axis_tvalid` (input, 1): Input payload valid.
- `s_axis_tready` (output, 1): Transmitter can accept a payload.
- `txd` (output, 1): UART serial output, idle high.
- `busy` (output, 1): Frame currently being transmitted.
- `prescale` (input, 16): Baud-rate prescale or bit timing control.

## Parameter semantics

- `DATA_WIDTH` default `8`: Number of payload bits per UART frame.
- `CLKS_PER_BIT` default `16`: Clock cycles per serial bit in simple fixed-baud implementations.

## Behavior model

- IDLE: Hold tx high, advertise ready, wait for valid payload.
- START: Drive start bit low for one bit time.
- DATA: Shift payload bits LSB first for DATA_WIDTH bit times.
- STOP: Drive stop bit high and return to idle.

## Usage constraints

- txd must idle high when reset or idle.
- Only accept new input when the transmitter is ready or idle.
- Data bits are transmitted LSB first unless the spec explicitly requests another order.
- Do not change txd faster than the configured bit period.

## Implementation notes

- Use a baud/prescale counter plus a bit counter; do not derive a separate generated clock for txd.
- Latch the input word at the start handshake so later input changes do not corrupt the frame.
- Represent the frame as start bit, DATA_WIDTH data bits, and stop bit, or use explicit START/DATA/STOP FSM states.
- Keep busy asserted from accepted input through the stop bit.

## Common errors

- Treating `source_refs` as code dependencies. They are provenance and learning references only.
- Changing handshake or reset polarity without updating the testbench and metadata.
- Reusing the template in a wider production design without reviewing timing, reset, and CDC assumptions.

## Verification checklist

- txd is high during reset and idle.
- A transmitted frame contains one low start bit, DATA_WIDTH LSB-first data bits, and one high stop bit.
- s_axis_tready or equivalent ready is low while the frame is in progress.
- busy deasserts after the stop bit completes.

## Files

- `module_info.json`: machine-readable metadata for retrieval and planning.
- `template.v`: minimal teaching RTL template.
- `examples/instantiation.v`: compact instantiation example.
- `examples/tb_uart_tx.v`: self-checking Icarus Verilog testbench.
