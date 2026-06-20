# axis_handshake_buffer

Ready/valid one-word skid or pipeline buffer for AXI-stream-like data paths.

This skill directory is self-contained for local teaching and simulation. `module_info.json` is the machine-readable index. `template.v` is a clean teaching implementation written for this repository; it is not copied from the external `source_refs`.

## When to use

- All accepted input payloads appear at the output exactly once and in order.
- m_axis_tdata remains stable during backpressure.
- axi stream
- ready valid
- skid buffer

Use this skill when the generated RTL needs the behavior described above and the constraints below match the target design.

## When not to use

- Avoid combinational ready/valid loops across module boundaries unless explicitly designed as bypass logic.
- Use skid storage when downstream ready can deassert after upstream has already observed ready.

Do not use this skill when the interface, timing model, or clock-domain assumptions differ materially from the template.

## Port semantics

- `clk` (input, 1): Clock.
- `rst` (input, 1): Reset valid storage.
- `s_axis_tdata` (input, DATA_WIDTH): Input payload.
- `s_axis_tvalid` (input, 1): Input valid.
- `s_axis_tready` (output, 1): Input ready.
- `m_axis_tdata` (output, DATA_WIDTH): Output payload.
- `m_axis_tvalid` (output, 1): Output valid.
- `m_axis_tready` (input, 1): Output ready.

## Parameter semantics

- `DATA_WIDTH` default `8`: Stream payload width.
- `REG_TYPE` default `skid`: Implementation style: bypass, simple, or skid.

## Behavior model

- Input transfers occur only when s_axis_tvalid and s_axis_tready are high on the same rising clock edge.
- Output transfers occur only when m_axis_tvalid and m_axis_tready are high on the same rising clock edge.
- Buffered payload and valid state are held stable while output valid is high and output ready is low.
- The buffer may bypass data when input and output handshakes occur in the same cycle.

## Usage constraints

- Do not drop valid data under downstream backpressure.
- Do not change m_axis_tdata while m_axis_tvalid is high and m_axis_tready is low.
- Avoid combinational ready/valid loops across module boundaries unless explicitly designed as bypass logic.
- Use skid storage when downstream ready can deassert after upstream has already observed ready.

## Implementation notes

- Implement at least one data register and one valid register for the simple-buffer form.
- Compute s_axis_tready from buffer vacancy or output acceptance.
- For skid mode, add temporary storage so a late ready deassertion does not lose the accepted word.
- Keep sideband signals, if any, registered with the same enable as tdata.

## Common errors

- Treating `source_refs` as code dependencies. They are provenance and learning references only.
- Changing handshake or reset polarity without updating the testbench and metadata.
- Reusing the template in a wider production design without reviewing timing, reset, and CDC assumptions.

## Verification checklist

- All accepted input payloads appear at the output exactly once and in order.
- m_axis_tdata remains stable during backpressure.
- s_axis_tready deasserts when the buffer cannot accept another word.
- Bypass cycles do not duplicate or skip payloads.

## Files

- `module_info.json`: machine-readable metadata for retrieval and planning.
- `template.v`: minimal teaching RTL template.
- `examples/instantiation.v`: compact instantiation example.
- `examples/tb_axis_handshake_buffer.v`: self-checking Icarus Verilog testbench.
