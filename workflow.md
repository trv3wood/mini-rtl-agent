# External RTL Skill Builder Workflow

This workflow is for growing the committed `skills/` library from high-quality open-source RTL without committing upstream repositories or unreviewed generated output.

## Directory Contract

```text
work/external_skills/   local upstream RTL checkouts, ignored by git
work/built_skills/      generated skill_builder output, ignored by git
skills/                 reviewed, commit-ready skill packages
```

`work/external_skills/` and `work/built_skills/` are intentionally git-ignored. Treat `work/built_skills/` as a staging area only.

## Source Repositories

Place local checkouts at these paths:

```text
work/external_skills/verilog-axis
work/external_skills/verilog-uart
work/external_skills/opentitan
work/external_skills/ibex
```

Download commands, to be run manually when the repos are not already present:

```sh
git clone https://github.com/alexforencich/verilog-axis.git work/external_skills/verilog-axis
git clone https://github.com/alexforencich/verilog-uart.git work/external_skills/verilog-uart
git clone https://github.com/lowRISC/opentitan.git work/external_skills/opentitan
git clone https://github.com/lowRISC/ibex.git work/external_skills/ibex
```

## Gate Policy

1. Run smoke extraction on a small set of relatively independent modules.
2. Inspect the generated `skill.json`, `compact_card.json`, copied RTL, and `report.json`.
3. If smoke output is structurally reasonable, run batch parsing for that upstream repo.
4. Promote only reviewed packages from `work/built_skills/...` into `skills/`.
5. Run `make skills` before committing promoted skills.

The builder is an extraction tool, not an IP quality certificate. A generated package is commit-worthy only after review.

The current accepted-skill gate is intentionally conservative:

- no duplicate module definitions
- self-contained and atomic: no dependency closure modules and no unresolved dependencies
- copied RTL total is at most 500 lines
- at most one detected state-machine `case` over a state/fsm signal
- generated package validates as minimal layout

Rejected candidates are recorded in `report.json` under `rejected_candidates`; they should not stop the batch run. A repo can therefore finish with both accepted skills and rejected candidates.

## Smoke Then Batch

Run all configured smoke tests:

```sh
scripts/smoke_external_skill_repos.sh
```

Run one repo only:

```sh
scripts/smoke_external_skill_repos.sh verilog-axis
scripts/smoke_external_skill_repos.sh verilog-uart
scripts/smoke_external_skill_repos.sh opentitan
scripts/smoke_external_skill_repos.sh ibex
```

For each repo, the script:

- builds a small temporary smoke repo under `work/generated/external_skill_smoke/<repo>/`
- runs `skill_builder` on the smoke repo
- validates generated minimal skill packages
- only then runs `skill_builder` on the full upstream checkout
- records rejected candidates without failing the whole run

Smoke output:

```text
work/built_skills/smoke/<repo>/
```

Batch output:

```text
work/built_skills/<repo>/
```

## Initial Smoke Module Set

The smoke list is intentionally conservative:

| Repo | Modules/files |
| --- | --- |
| `verilog-axis` | `rtl/arbiter.v`, `rtl/priority_encoder.v`, `rtl/axis_register.v`, `rtl/axis_fifo.v` |
| `verilog-uart` | `rtl/uart_tx.v`, `rtl/uart_rx.v` |
| `opentitan` | `hw/ip/prim_generic/rtl/prim_flop_2sync.sv`, `hw/ip/prim/rtl/prim_pulse_sync.sv`, `hw/ip/prim/rtl/prim_lfsr.sv` |
| `ibex` | `rtl/ibex_counter.sv`, `rtl/ibex_csr.sv` |

If an upstream repo changes paths or a module has package/include dependencies that make extraction noisy, adjust the smoke list before batch parsing. Prefer smaller independent modules over top-level cores for this phase.

Batch roots are repo-specific:

- `verilog-axis`: full checkout
- `verilog-uart`: `rtl/` only, excluding board examples
- `opentitan`: copied primitive RTL from `hw/ip/prim/rtl` and `hw/ip/prim_generic/rtl`
- `ibex`: full checkout, with quality gates filtering non-atomic modules

## Promotion

After reviewing a generated package:

```sh
cp -a work/built_skills/<repo>/<skill_name> skills/<skill_name>
make skills
```

Do not bulk-copy all generated skills into `skills/`. Keep `skills/` curated and commit-ready.
