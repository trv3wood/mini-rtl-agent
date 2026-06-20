# round_robin_arbiter

Fair arbiter that grants one of N requesters and rotates priority after successful grant.

This skill directory is self-contained for local teaching and simulation. `module_info.json` is the machine-readable index. `template.v` is a clean teaching implementation written for this repository; it is not copied from the external `source_refs`.

## When to use

- grant is one-hot whenever grant_valid is high.
- No grant bit is asserted unless the matching request bit is high.
- arbiter
- round robin
- fairness

Use this skill when the generated RTL needs the behavior described above and the constraints below match the target design.

## When not to use

- A continuously requesting port must eventually receive service if other grants are acknowledged.
- Define whether grants are combinational or registered before integrating into a timing-sensitive bus.

Do not use this skill when the interface, timing model, or clock-domain assumptions differ materially from the template.

## Port semantics

- `clk` (input, 1): Clock.
- `rst` (input, 1): Reset priority pointer.
- `request` (input, PORTS): Requester bits.
- `acknowledge` (input, 1): Current grant was accepted; rotate priority.
- `grant` (output, PORTS): One-hot grant.
- `grant_valid` (output, 1): At least one request is granted.
- `grant_encoded` (output, $clog2(PORTS)): Encoded winning index.

## Parameter semantics

- `PORTS` default `4`: Number of requesters.
- `LOCK_ENABLE` default `0`: Optional hold grant until transaction completes.

## Behavior model

- When one or more request bits are high, grant exactly one eligible requester.
- After an acknowledged grant, priority advances so the next scan starts after the granted requester.
- If no requests are active, grant_valid is low and grant is zero.
- Optional lock mode holds a grant until the selected transaction completes.

## Usage constraints

- grant must be one-hot or all-zero; never grant two requesters at once.
- Do not rotate priority on idle cycles or unaccepted grants.
- A continuously requesting port must eventually receive service if other grants are acknowledged.
- Define whether grants are combinational or registered before integrating into a timing-sensitive bus.

## Implementation notes

- Keep a priority pointer for the requester after the last accepted grant.
- Use masked priority selection above the pointer first, then wrap to lower indexes.
- Generate both one-hot grant and encoded grant from the same selected index.
- Update the pointer only when grant_valid and acknowledge are both true.

## Common errors

- Treating `source_refs` as code dependencies. They are provenance and learning references only.
- Changing handshake or reset polarity without updating the testbench and metadata.
- Reusing the template in a wider production design without reviewing timing, reset, and CDC assumptions.

## Verification checklist

- grant is one-hot whenever grant_valid is high.
- No grant bit is asserted unless the matching request bit is high.
- With all requests held high, grants rotate through all ports fairly.
- Priority pointer does not advance without an acknowledged grant.

## Files

- `module_info.json`: machine-readable metadata for retrieval and planning.
- `template.v`: minimal teaching RTL template.
- `examples/instantiation.v`: compact instantiation example.
- `examples/tb_round_robin_arbiter.v`: self-checking Icarus Verilog testbench.
