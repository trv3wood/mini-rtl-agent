# reset_synchronizer

A reset synchronizer primitive with asynchronous assertion and synchronous deassertion in the destination clock domain.

This skill directory is self-contained for local teaching and simulation. `module_info.json` is the machine-readable index. `template.v` is a clean teaching implementation written for this repository; it is not copied from the external `source_refs`.

## When to use

- rst_out is active whenever rst_in is active.
- rst_out never deasserts except on clk rising edge.
- reset
- reset synchronizer
- cdc

Use this skill when the generated RTL needs the behavior described above and the constraints below match the target design.

## When not to use

- Do not use this primitive to synchronize arbitrary data buses.
- Do not use this primitive as a general pulse synchronizer.

Do not use this skill when the interface, timing model, or clock-domain assumptions differ materially from the template.

## Port semantics

- `clk` (input, 1): Destination clock domain.
- `rst_in` (input, 1): Incoming asynchronous or external reset.
- `rst_out` (output, 1): Reset synchronized for release in the clk domain. It uses the same active polarity as rst_in.

## Parameter semantics

- `STAGES` default `2`: Number of flip-flop stages. Must be >= 2 for normal CDC use.
- `RESET_ACTIVE_LEVEL` default `1`: Active level of rst_in and rst_out. 1 means active-high reset, 0 means active-low reset.

## Behavior model

- When rst_in is active, rst_out becomes active immediately or through an asynchronous reset path.
- When rst_in becomes inactive, the inactive value shifts through STAGES flip-flops.
- rst_out deasserts only on a rising edge of clk after STAGES cycles.

## Usage constraints

- Use asynchronous assertion and synchronous deassertion.
- Use at least two synchronizer stages unless the design has a documented reason.
- Instantiate one reset synchronizer per destination clock domain.
- Do not use this primitive to synchronize arbitrary data buses.
- Do not use this primitive as a general pulse synchronizer.

## Implementation notes

- Parameterize polarity so rst_in and rst_out are both active-high when RESET_ACTIVE_LEVEL=1 and both active-low when RESET_ACTIVE_LEVEL=0.
- Use a shift register initialized to the active reset value on assertion.
- On each clk edge after deassertion, shift in the inactive reset value until rst_out releases.
- Apply async_reg or equivalent synthesis attributes to the synchronizer stages when supported by the flow.

## Common errors

- Treating `source_refs` as code dependencies. They are provenance and learning references only.
- Changing handshake or reset polarity without updating the testbench and metadata.
- Reusing the template in a wider production design without reviewing timing, reset, and CDC assumptions.

## Verification checklist

- rst_out is active whenever rst_in is active.
- rst_out never deasserts except on clk rising edge.
- rst_out deassertion latency matches STAGES.
- rst_out polarity matches RESET_ACTIVE_LEVEL.

## Files

- `module_info.json`: machine-readable metadata for retrieval and planning.
- `template.v`: minimal teaching RTL template.
- `examples/instantiation.v`: compact instantiation example.
- `examples/tb_reset_synchronizer.v`: self-checking Icarus Verilog testbench.
