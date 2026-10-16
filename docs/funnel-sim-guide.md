# Funnel Simulation User Guide

How to run a funnel scenario end-to-end in EVE-MIRO, and how to read
what comes out. This covers the `funnel-sim` CLI command. For the
business model behind the parameters, see
`~/workspace/moovsoon/worker-4-simulation.md`.

## What the funnel loop does

One command runs the full reality-grounded loop for the funnel:

1. **Ground** — loads baseline parameters from the fixture
   (`datasets/fixtures/funnel_baseline.json`) with provenance labels
   (proposal figures; vendor-reported where labeled). If the fixture is
   missing or malformed, the command fails closed instead of inventing
   baseline data.
2. **Simulate** — runs the funnelsim engine (customer lifecycle agents
   plus mover office agents, or pre-job leads in speed-to-lead mode)
   under one of the scenarios in `experiments/funnel/`. Every outcome
   after t0 is SIMULATED.
3. **Record** — writes the run to the ledger as projection-only
   (verdict PENDING). There is no observed t1 yet, so no alignment
   score is computed or claimed. When pilot data exists, align the
   predicted series against it.
4. **Summarize** — prints jobs, reviews gained, share lift, conversion,
   problems routed/resolved, opt-out rate, cost, revenue, and margin,
   and writes the full summary to
   `storage/funnel/latest_funnel_run.json`.

## Running the CLI

```bash
eve-miro funnel-sim
eve-miro funnel-sim --scenario funnel_pessimistic_001 --months 3
eve-miro funnel-sim --scenario funnel_speed_to_lead_001 --months 1
```

Flags:

- `--scenario`: any scenario id from the `experiments/funnel/`
  registry (default: `funnel_base_001`). The registry is the YAML
  directory: adding a file makes it runnable.
- `--months` — simulated horizon in months of 30 days, minimum 1
  (default: 3).
- `--fixture-dir` — override the fixture directory (used by tests).

The run is fully offline. Each scenario runs twice (two seeds) and the
reported metrics are the mean.

## Reading the output

- `reviews_gained` — incremental reviews over the horizon (the R in
  R = N * c * k).
- `incremental_share_pp` — reviews divided by jobs, in percentage
  points. Add the 18% organic baseline for the implied total share.
- `conversion` — reviews per contacted customer. Compare against the
  scenario's `review_conversion` parameter.
- `problems_routed` / `problems_resolved` — the problem-capture loop;
  resolved problems are the margin story.
- `opt_out_rate` — sustained values above 5% are a kill signal.
- `margin_pct` — at the default pricing the base case runs ~90%+;
  pricing power and conversion move it, not text costs.

## Scenarios

| scenario | what it is |
|---|---|
| `funnel_base_001` | 3 movers, 60 jobs/mo, 80% coverage, 20% conversion |
| `funnel_pessimistic_001` | 45 jobs/mo, 65% coverage, 12% conversion |
| `funnel_optimistic_001` | 80 jobs/mo, 90% coverage, 26% conversion |
| `funnel_speed_to_lead_001` | 14-day pre-job experiment, 10 leads/day/mover |

Interventions (`carrier_crackdown`, `google_enforcement`,
`office_slowdown`) can be added to any scenario's YAML to stress-test
it; see `funnelsim/README.md`.
