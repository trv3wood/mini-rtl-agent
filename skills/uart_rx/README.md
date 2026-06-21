# uart_rx

UART receiver that detects a start bit, samples serial data near bit centers, and emits received words with error flags.

This skill directory is self-contained for local teaching and simulation. `module_info.json` is the machine-readable index. `template.v` is a clean teaching implementation written for this repository; it is not copied from the external `source_refs`.

## When to use

- A legal frame produces exactly one valid output word with the expected data.
- Invalid stop bit raises frame_error and does not silently accept the byte.
- uart
- rx
- receiver

Use this skill when the generated RTL needs the behavior described above and the constraints below match the target design.

## When not to use

- Hold output valid until the downstream ready handshake consumes the word.
- Raise frame_error when the stop bit is sampled low.

Do not use this skill when the interface, timing model, or clock-domain assumptions differ materially from the template.

## Port semantics

- `clk` (input, 1): System clock.
- `rst` (input, 1): Synchronous reset.
- `m_axis_tdata` (output, DATA_WIDTH): Received payload word.
- `m_axis_tvalid` (output, 1): Received payload is valid.
- `m_axis_tready` (input, 1): Consumer accepted payload.
- `rxd` (input, 1): UART serial input, idle high.
- `busy` (output, 1): Receiver is inside a frame.
- `overrun_error` (output, 1): New byte arrived before previous byte was consumed.
- `frame_error` (output, 1): Stop bit was not high.
- `prescale` (input, 16): Baud-rate prescale or bit timing control.

## Parameter semantics

- `DATA_WIDTH` default `8`: Number of payload bits to receive.

## Behavior model

- IDLE: Wait for rxd to go low.
- START_CHECK: Delay half a bit and confirm start bit is still low.
- DATA: Sample DATA_WIDTH data bits at bit centers.
- STOP: Sample stop bit and raise valid or frame_error.

## Usage constraints

- rxd must be treated as an external serial input and registered before control decisions.
- Sample data near the center of each bit period, not immediately on the detected edge.
- Hold output valid until the downstream ready handshake consumes the word.
- Raise frame_error when the stop bit is sampled low.

## Implementation notes

- Detect a falling edge or low level on idle-high rxd, then wait half a bit before validating the start bit.
- Use a prescale counter for sample timing and a bit counter for DATA_WIDTH payload bits.
- Shift sampled serial bits into the receive register LSB first.
- Gate overrun_error with an unconsumed previous output word.

## Common errors

- Treating `source_refs` as code dependencies. They are provenance and learning references only.
- Changing handshake or reset polarity without updating the testbench and metadata.
- Reusing the template in a wider production design without reviewing timing, reset, and CDC assumptions.

## Verification checklist

- A legal frame produces exactly one valid output word with the expected data.
- Invalid stop bit raises frame_error and does not silently accept the byte.
- Backpressure on the output can produce overrun_error on a second received byte.
- busy is asserted only while a frame is being received.

## Files

- `module_info.json`: machine-readable metadata for retrieval and planning.
- `template.v`: minimal teaching RTL template.
- `examples/instantiation.v`: compact instantiation example.
- `examples/tb_uart_rx.v`: self-checking Icarus Verilog testbench.
