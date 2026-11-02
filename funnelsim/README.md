# FunnelSim

A purpose-built funnel simulation engine (MIT, first-party). It grounds
agent-based funnel scenarios in the MSTech proposal's baseline figures and
produces SIMULATED outcome distributions for the Moovloop post-job SMS
loop and the SMS speed-to-lead experiment. It is not a forecast of
business results.

## Layout

```
funnelsim/
  agents.py      customer lifecycle + mover office agents (seed-deterministic)
  economics.py   per-text / 10DLC / pricing arithmetic (values flow in via scenario)
  engine.py      FunnelSimEngine behind the SimulationEngine protocol
  scenarios.py   programmatic Scenario builder (canonical YAML in experiments/funnel/)
```

`funnelsim` never imports from `mirofish/` (AGPL-3.0). It only depends on
the MIT data fabric (`eve_miro.*`) for the `SimulationEngine` protocol and
world models.

## How a run works

1. `FunnelSimEngine.initialize(world, population)` reads the scenario's
   `conditions` (mode, jobs/leads, probabilities, pricing). Missing or
   invalid parameters raise `EngineNotConfigured` (fail closed, never a
   silent stub). `agents.population` is the number of pilot movers.
2. Each step is one simulated day: shock interventions due that day apply
   first, then arrivals, nudges, terminal draws, office resolutions, and
   the day's economics are posted. Agents only ever see history up to the
   current day (no lookahead).
3. `run()` finalizes a `SimulationResult` with daily cumulative series
   (`reviews_per_100`, `problems_routed`, `cost`, `revenue`,
   `opt_out_rate`, plus `bookings_per_100_leads` in speed-to-lead mode),
   per-customer traces, and a summary. Every element of
   `predicted_series` is SIMULATED; the baseline parameters are observed
   fixture context.

## Customer lifecycle

`UNCONTACTED -> TEXTED -> REVIEWED | OPTED_OUT | PROBLEM_REPORTED |
SILENT`, with `NOT_CONTACTABLE` terminal for jobs without a usable mobile
number. `PROBLEM_REPORTED` customers go to the mover's office agent, which
resolves them (before they go public) with a configured probability and an
exponential latency draw.

Outcome draws are mutually exclusive from one uniform variate, so the
unconditional review probability among contacted customers equals the
scenario's `review_conversion` k exactly, matching the closed-form
R = N * c * k. Throughput: thank-you + ask (2 texts), nudge (1),
office routing text on problems (1).

## Modes

- `post_job` (default): jobs arrive per mover per month; the loop runs;
  economics are per-job base plus per-review / per-problem outcome bonuses.
- `speed_to_lead`: pre-job leads arrive per day; covered leads get an
  instant SMS (response ~1 min mean) vs the uncovered baseline (~8 min);
  booking probability depends on the response-time bucket (<= 5 min vs
  slower). Economics are per-booking bonuses.

## Interventions

| type | extra fields | effect |
|---|---|---|
| `carrier_crackdown` | `opt_out_multiplier` (default 5.0), `duration_days` (default 14) | multiplies the daily opt-out probability |
| `google_enforcement` | `max_reviews_per_day` (default 3.0), `duration_days` | reviews beyond the cap are flagged, not counted |
| `office_slowdown` | `response_time_multiplier` (default 3.0), `duration_days` (default 30) | stretches office resolution latency |

Scenario YAMLs live in `experiments/funnel/`: `funnel_base_001`,
`funnel_pessimistic_001`, `funnel_optimistic_001` (the three worker-4
parameter variants) and `funnel_speed_to_lead_001` (the month-1
experiment). The engine factory (`get_simulation_engine`) routes
`scenario.type == "funnel"` to FunnelSimEngine when engines are in-tree;
stub mode and all other scenarios are unchanged.

## Honest limitations

- **Parameter assumptions, not estimates.** Conversion, coverage, and
  pricing are proposal/worker-4 assumptions with provenance in
  `datasets/fixtures/funnel_baseline.json`, not measured pilot data.
  The trust ledger is where the sim earns credibility: align these
  projections against pilot reality when it exists.
- **No behavioral adaptation.** Agents follow fixed rules for a run. Real
  customers adapt to repeated texts; offices change behavior under
  measurement.
- **Edge effects.** Customers texted in the last 4 days of the horizon
  never reach their terminal draw (the nudge window). Negligible at
  90 days; visible at very short horizons.
- **Not a forecast.** Output is distributions of outcomes under stated
  scenarios, never "this will happen".
