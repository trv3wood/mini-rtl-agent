# axis_pipeline_fifo

AXI-stream pipeline FIFO/register slice for timing closure.

## When to use

Use this skill when the request is about breaking a long ready/valid timing path, inserting AXI-stream pipeline stages, adding controlled latency, or implementing a register slice.

## When not to use

Do not use it as a deep burst buffer; choose `axis_fifo`. Do not use it for SRL/LUT-style shallow queue optimization; choose `axis_srl_fifo`. Do not use it for CDC.

## Verification checklist

- Backpressure propagates to the input when pipeline stages are full.
- Output payload is stable while stalled.
- Accepted words exit in order.
- The pipeline resumes without duplicating or dropping words.
