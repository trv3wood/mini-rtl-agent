# mini-rtl-agent

A compact RTL skill-builder and skill-retriever playground.

The current project focus is deliberately narrow:

- `skill_builder`: turn local open-source Verilog/SystemVerilog repositories into small, atomic RTL skill packages.
- `skill_retriever`: retrieve those skills from either a strict `query_plan.json` or an LLM-generated query plan.

The older HDL agent demo and the external SkillRouter comparison path remain in the repository, but they are secondary to this builder/retriever workflow.

## Requirements

- Python 3.10+
- `ripgrep` (`rg`) for retrieval
- Optional: `iverilog` and `vvp` for HDL syntax/simulation demos
- Optional: an OpenAI-compatible LLM endpoint for user-query planning and semantic skill annotation

Create `.env` from the example when using an LLM:

```sh
cp .env.example .env
```

Supported variables:

```sh
LLM_API_KEY=...
LLM_BASE_URL=https://api.example.com/v1
LLM_MODEL=provider-model-name
LLM_TIMEOUT_SECONDS=60
```

`src/utils/llm.py` loads `.env` with `python-dotenv`; provider-specific names are intentionally avoided.

## Repository Layout

```text
src/skill_builder/      Build compact RTL skills from local RTL repositories
src/skill_retriever/    Query-plan based deterministic skill retriever
skills/                 Reviewed, commit-ready RTL skills
benchmarks/             Small retriever regression and semantic query cases
work/external_skills/   Ignored upstream RTL checkouts
work/built_skills/      Ignored generated skill packages
work/generated/         Ignored HDL-agent outputs
work/reports/           Ignored generated reports
```

## Skill Package

A reviewed skill under `skills/` has this compact shape:

```text
skills/<skill>/
  skill.json
  compact_card.json
  rtl/<skill>.v
```

- `compact_card.json` is the router-facing retrieval card.
- `skill.json` is the structured skill metadata consumed after routing.
- `rtl/` contains the small reference RTL payload.

The deterministic retriever searches `compact_card.json` files. It does not rely on README text, generated reports, or model-side final skill selection.

Validate the committed skill library:

```sh
make skills
```

## Skill Builder

`skill_builder` converts a local RTL repository into minimal skill packages.

Basic run:

```sh
.venv/bin/python -m skill_builder build <repo_path> \
  --output work/built_skills/<repo_name> \
  --clean
```

Local sample:

```sh
make skill-builder-demo
```

The builder pipeline:

- Recursively scans `*.v`, `*.sv`, `*.vh`, and `*.svh`.
- Extracts modules, parameters, ports, comments, likely FSMs, instances, and common patterns.
- Builds dependency closures for candidate modules.
- Writes only `skill.json`, `compact_card.json`, and copied RTL under `rtl/`.
- Writes `report.json` with accepted and rejected candidates.
- Keeps running when candidates are rejected.

Accepted-skill gates are intentionally strict:

- No duplicate module definitions inside one skill.
- Self-contained, atomic RTL only.
- At most 500 copied RTL lines.
- At most one detected state-machine `case` over a state/FSM signal.

Semantic annotation uses the shared LLM client when `LLM_*` is configured. If the provider returns an error, the report records the fallback path explicitly.

External-library workflow:

```sh
git clone --depth 1 https://github.com/alexforencich/verilog-axis.git work/external_skills/verilog-axis
git clone --depth 1 https://github.com/alexforencich/verilog-uart.git work/external_skills/verilog-uart
git clone --depth 1 https://github.com/lowRISC/opentitan.git work/external_skills/opentitan
git clone --depth 1 https://github.com/lowRISC/ibex.git work/external_skills/ibex
```

Then run smoke/batch parsing:

```sh
scripts/smoke_external_skill_repos.sh
```

Policy:

```text
raw upstream RTL -> work/external_skills/     ignored by git
generated skills -> work/built_skills/       ignored by git
reviewed skills  -> skills/                  commit-ready
```

See `workflow.md` for the full smoke -> batch -> review -> promote process.

Recent external-library builder results with the atomic gates:

| Repo | RTL files | Modules | Accepted skills | Rejected candidates |
| --- | ---: | ---: | ---: | ---: |
| `verilog-axis` | 85 | 31 | 20 | 11 |
| `verilog-uart` | 30 | 28 | 2 | 26 |
| `opentitan` primitives | 203 | 121 | 71 | 50 |
| `ibex` | 640 | 209 | 88 | 121 |

## Skill Retriever

`skill_retriever` is a strict two-stage layer:

```text
natural language request
  -> LLM-generated query_plan.json
  -> deterministic rg/scoring over compact_card.json
  -> ranked skills with reasons
```

The retriever itself only accepts structured query plans. Natural-language rewriting is upstream LLM-agent responsibility.

Required `query_plan.json` schema:

```json
{
  "intent": "design a UART transmitter",
  "positive_terms": ["uart", "transmitter", "ready", "valid"],
  "negative_terms": [],
  "likely_categories": ["uart", "serial", "transmitter"],
  "likely_interfaces": ["ready_valid_handshake", "busy_signal"],
  "required_features": ["uart_transmitter", "ready_valid_input"]
}
```

Generate a plan from a user request:

```sh
.venv/bin/python -m skill_retriever plan \
  "Create a byte sender for an asynchronous serial line with flow control"
```

Run the full user-query path:

```sh
.venv/bin/python -m skill_retriever query \
  "Create a byte sender for an asynchronous serial line with flow control" \
  --skills-root skills \
  --limit 5
```

Run deterministic retrieval from an existing plan:

```sh
.venv/bin/python -m skill_retriever search query_plan.json \
  --skills-root skills

.venv/bin/python -m skill_retriever search query_plan.json \
  --skills-root skills \
  --format json
```

Table output:

```text
rank  score  skill  category  why
```

JSON output:

```json
{
  "query_plan": {},
  "results": [
    {
      "name": "uart_tx",
      "path": "skills/uart_tx",
      "score": 129,
      "category": "uart",
      "interfaces": [],
      "patterns": [],
      "why_matched": [],
      "penalties": []
    }
  ]
}
```

Ranking is deterministic:

- Search uses `positive_terms` with `rg`.
- Candidates are loaded from matched `compact_card.json` files.
- Scoring uses compact-card fields such as `core_function`, `algorithm`, `structure`, `keywords`, `retrieval_text`, `interface_signature`, and `granularity`.
- `likely_categories`, `likely_interfaces`, and `required_features` add structured evidence.
- `negative_terms` add penalties.
- Ties sort by score descending, then skill name, then path.

LangChain integration exposes the deterministic retriever as a tool:

- Tool name: `retrieve_rtl_skills`
- Input: the query-plan fields plus optional `skills_root` and `limit`
- Output: JSON-serializable ranked results
- No LLM call inside the tool

## Retriever Checks

Curated query-plan benchmark:

```sh
.venv/bin/python -m skill_retriever benchmark benchmarks/router_benchmark.json \
  --skills-root skills \
  --limit 10
```

Semantic user-query benchmark, useful for checking whether the LLM can infer terms that are not directly written by the user:

```sh
.venv/bin/python -m skill_retriever user-benchmark benchmarks/semantic_user_queries.json \
  --skills-root work/built_skills \
  --max-cases 1 \
  --limit 5
```

Use `--max-cases 1` for a cheap smoke. Remove it when running a fuller LLM-backed check.

## HDL Agent Boundary

The HDL agent is an end-to-end demo on top of the current `skills/` library. It is useful for checking whether a user request can be routed to a skill and customized into standalone RTL.

```sh
.venv/bin/python -m hdl_agent \
  "Create a small UART transmitter with ready/valid input and busy output" \
  --show-trace
```

It uses:

```text
user request -> query plan -> retriever -> selected skill context -> generated HDL -> iverilog syntax check
```

Generated HDL is written under `work/generated/`. The CLI prints the important actions as they happen:

- build `query_plan.json` from the request
- invoke the skill retriever tool
- show retrieved skill candidates and scores
- select the top skill
- generate RTL from `skill.json`, `compact_card.json`, and source RTL
- run `iverilog -g2012 -Wall`
- feed compiler errors back to the LLM for up to three repair attempts
- write the final RTL path

Example IP customization request:

```sh
.venv/bin/python -m hdl_agent \
  "Create IP named custom_priority8 that converts an 8-bit request vector into a valid flag and encoded winning index." \
  --skills-root skills \
  --output work/generated/custom_priority8.v \
  --show-trace
```

For this case the agent routes to `skills/priority_encoder` and emits a standalone wrapper-style IP:

- fixes `WIDTH=8`
- fixes `LSB_HIGH_PRIORITY=0`, giving MSB priority
- renames the user-facing ports to `req`, `valid`, and `win_idx`
- hides the original one-hot output by leaving `output_unencoded` unconnected
- keeps the reusable `priority_encoder` implementation in the generated file so it can compile by itself

This path is still a demo surface, not a replacement for the builder/retriever evaluation. Current tests cover several customization targets from existing skills: UART TX, AXI-stream register slice, priority encoder, one-hot encoder, and reset synchronizer.

## External SkillRouter Boundary

`external/SkillRouter/` is an ignored third-party research project used only for optional comparison. It is not required for the default builder or retriever commands.

## Test

Run the repository tests:

```sh
.venv/bin/python -m pytest -q
```

The tests focus on structured IO, deterministic retrieval behavior, CLI output, LangChain tool import/invocation when installed, and builder package generation.

## Known Limits

- The builder is a compact extraction tool, not an IP quality certification system.
- SystemVerilog support is practical and partial; complex packages, interfaces, and generate-heavy code can still be under-extracted.
- FSM counting is a lightweight static heuristic.
- Semantic labels depend on the configured LLM and may vary by model.
- Reviewed skills should be promoted manually from `work/built_skills/` into `skills/`.
