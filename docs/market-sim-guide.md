# Market Simulation User Guide

How to run a market scenario end-to-end in EVE-MIRO, and how to read
what comes out. This covers the Phase 4 CLI command and dashboard
panel. For the metric definitions, see `docs/market-alignment.md`.

## What the market loop does

One command runs the full reality-grounded loop for markets:

1. **Ground** — builds WorldState(t0) from OBSERVED fixture bars
   (`datasets/fixtures/markets_bars.json`) via the Phase 1 market
   snapshot builder. Initial prices come from the fixture.
2. **Simulate** — runs the marketsim engine (limit order book plus
   market-maker, momentum, noise, and fundamental archetypes) under one
   of the shock scenarios in `experiments/market/`. Every price after
   t0 is SIMULATED.
3. **Align** — compares the simulated daily paths against a held-out
   fixture window (the observed t1) with the Phase 3 alignment
   metrics: return-distribution KS, rolling vol-path MAE, and
   drawdown-depth error.
4. **Trust** — records the alignment to the ledger and prints the
   per-scenario-class trust summary: USE, CAUTION, or DO_NOT_USE.

## Running the CLI

```bash
eve-miro market-sim
eve-miro market-sim --scenario vol_spike_001 --hours 120
```

Flags:

- `--scenario` — one of `sell_shock_001`, `vol_spike_001`,
  `rate_shock_001` (default: `sell_shock_001`). These are the scenario
  definitions in `experiments/market/`; the CLI remaps their synthetic
  symbols onto the fixture tickers and scales size-based shock
  quantities by the price ratio so the shock stays economically
  comparable.
- `--hours` — simulated horizon in hours, minimum 72 (needs at least
  3 daily bars to align against). Default: 120.
- `--fixture-dir` — override the fixture directory (used by tests).

The run is fully offline. If the fixture file is missing, or the
fixture is too short for the requested horizon, the command fails
closed with a clear message instead of inventing data.

The summary is printed to stdout and written to
`storage/market/latest_market_run.json`, which feeds the dashboard.

## Running from the dashboard

The dashboard Market tab has a control row above the results: a
scenario dropdown, an hours input, and a Run button. Pressing Run
calls `POST /market/run` with the same shared run function the CLI
uses, disables the button while the run executes (about 15 seconds
for 72 hours), then refreshes the tab with the new results. The
run's disclaimer renders at the bottom of the tab, and the
SIMULATED/OBSERVED badges stay on every chart. On failure the tab
shows the plain error message and the button re-enables; nothing is
fabricated.

## Reading the trust output

Example (abridged):

```text
market-sim  scenario=sell_shock_001  hours=72  symbols=AAPL,SPY
aggregate alignment score: 0.0382  (class=sell_shock)
  AAPL: score=0.0000  ks=1.0000  vol_mae=0.0272  dd_err=0.0476
scenario-class trust:
  [DO_NOT_USE] sell_shock  score=0.3000
    for scenario class sell_shock, over 2 past alignments, the sim's
    drawdown predictions were within 2.00% of observed 50% of the time
    (1 of 2).
```

- The **aggregate score** is the mean per-symbol alignment score for
  this run. It measures calibration against one realized window.
- The **per-class trust** answers: over past alignments, how often did
  this scenario class reproduce realized drawdowns within tolerance?
  Classes with no alignments are DO_NOT_USE, loudly. A high score for
  `sell_shock` means past shock scenarios landed near what happened;
  it does not mean the next shock is predicted.

The dashboard **Market** tab shows the same data: the trust table, and
per-symbol simulated-vs-observed sparklines with the three metrics.
It reads from `GET /market/latest`, which 404s until a CLI run has
been recorded.

## Honest limitations

- Alignment is scored against **one realized path**. A single draw
  cannot validate a distribution; it can only fail to falsify it.
- **Exogenous news is unmodeled.** If the held-out window was driven
  by a surprise the sim cannot generate, the score punishes the sim
  for the world's randomness, not for a modeling error.
- Simulated hourly mids are downsampled to daily closes before
  alignment, to match the daily fixture bars. Intraday dynamics are
  not compared.
- Scenario symbols are remapped from the synthetic ACME/BETA in the
  YAML definitions onto real fixture tickers; shock quantities are
  price-scaled, not re-calibrated.
- Low scores are the normal outcome here. A DO_NOT_USE verdict is the
  system working as designed: it tells you to widen the shock
  parameters, add archetypes, or stop quoting the scenario's numbers.
