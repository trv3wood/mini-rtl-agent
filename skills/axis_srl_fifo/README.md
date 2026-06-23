# axis_srl_fifo

Small AXI-stream FIFO for SRL or shift-register style buffering.

## When to use

Use this skill when the request emphasizes shallow stream buffering, SRL inference, LUT/LUTRAM implementation, small depth, or low-resource FPGA buffering with `tvalid`/`tready`.

## When not to use

Do not use it for large burst queues; choose `axis_fifo`. Do not use it for a pure timing pipeline; choose `axis_pipeline_fifo`. Do not use it for CDC.

## Verification checklist

- The oldest accepted stream word exits first.
- Full shallow storage deasserts `s_axis_tready`.
- Stalled output holds `m_axis_tdata`.
- Shift and append in the same cycle keep occupancy correct.
