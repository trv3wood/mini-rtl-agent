# axis_fifo

AXI-stream ready/valid FIFO for same-clock elastic buffering.

## When to use

Use this skill when a stream path needs more than a one-word buffer: burst absorption, queueing, preserved `tdata` order, `tvalid`/`tready` backpressure, and optional occupancy tracking.

## When not to use

Do not use it for clock-domain crossing; choose `async_fifo`. Do not use it for only one pipeline cut; choose `axis_handshake_buffer` or `axis_pipeline_fifo`. Do not use it for explicitly SRL/LUT-optimized tiny FIFOs; choose `axis_srl_fifo`.

## Verification checklist

- Accepted input words are emitted exactly once and in order.
- `m_axis_tdata` is stable while stalled.
- `s_axis_tready` reflects full or simultaneous output acceptance.
- Occupancy count matches fill, drain, and simultaneous transfers.
