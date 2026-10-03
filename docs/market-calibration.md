# Market simulator calibration (MSM)

This document describes how the marketsim trader archetypes are calibrated
with the simulated method of moments (MSM). Calibration tunes the
simulator's mechanism; it does not predict prices.

## What MSM does here

We choose a vector of agent parameters (9 free parameters across the four
archetypes: market maker, momentum, noise, fundamental), simulate the
baseline market under those parameters, compute 16 summary moments from the
simulated daily closes, and minimize the weighted distance between those
moments and the same moments computed from real history (SPY, 2019-2023).
The fitted parameters are the ones whose simulated market "looks like" the
real market on those statistics.

The optimizer is Nelder-Mead (via scipy) plus threshold-accepting rounds,
the Dicks and Gebbie recipe from the calibration literature. See
`eve-miro-research/ml-architecture-survey.md` for the architecture survey
that ranked MSM first and for the rejected alternatives (GANs, neural SDEs,
diffusion LOB models) with reasons.

## Pre-registration

`experiments/market/calibration_prereg.json` declares, before any
optimization: the 16-moment list with scales and weights, the 9-parameter
vector with bounds and starting values, the optimizer configuration, the
simulation budget, and the validation plan. The file is marked frozen.
Changing moments, bounds, weights, or optimizer settings after seeing
results invalidates the calibration; any change requires a new dated
prereg file.

Moment list (all from the fit targets file, no raw data needed at fit time):

- log-return std, excess kurtosis, skew, mean
- absolute-return autocorrelation at lags 1, 5, 10, 20 (volatility clustering)
- realized-vol (5d and 20d, annualized): mean, std, and percentile-grid MAE
- Hill tail index, left and right 5 percent tails

Drawdown is a reported diagnostic only, not an optimized moment: the
target drawdown distribution is computed over 252-day windows while the
calibration simulates 126-day windows. Overnight-gap statistics are
excluded because the hourly simulator has no overnight session.

## The holdout rule

The fit targets cover 2019-01-01 to 2023-12-31. The holdout period
(2024-01-01 to latest) must never influence fitting. This is enforced
structurally: `load_fit_targets` strips holdout metadata and refuses
payloads carrying holdout-derived statistics, and the fitting code path
accepts only the fit targets file. Holdout validation is a separate CLI
mode (`market-calibrate validate`) that computes the same moments on
holdout raw bars once, after optimization, and reports fit vs holdout
errors side by side. It never feeds the optimizer.

## How to run

Fit (writes `storage/market/calibration_result.json`):

```bash
eve-miro market-calibrate fit \
  --targets /path/to/targets_fit.json \
  --out storage/market/calibration_result.json \
  --starts 3
```

`--starts` runs the search from 1 to 3 starting points (prereg start,
low corner, high corner of unit space) for the degeneracy analysis.
Each start runs Nelder-Mead (max 400 evaluations) followed by threshold
accepting (3 rounds, 3 tries per round, at most 100 inner evaluations
each). The threshold-accepting inner budget is an implementation choice;
the prereg specifies the optimizer family, not the exact counts.

### Checkpointed per-start runs (recommended for long searches)

A full 3-start search takes on the order of an hour and a half at 32
agents, 126 days, 24 steps/day, and 3 replications per evaluation. To
survive interruptions, run each start separately so it checkpoints its
result the moment it finishes, then merge:

```bash
eve-miro market-calibrate fit --targets /path/to/targets_fit.json \
  --out storage/market/checkpoints/start0.json --start-index 0
eve-miro market-calibrate fit --targets /path/to/targets_fit.json \
  --out storage/market/checkpoints/start1.json --start-index 1
eve-miro market-calibrate fit --targets /path/to/targets_fit.json \
  --out storage/market/checkpoints/start2.json --start-index 2
eve-miro market-calibrate combine \
  --inputs storage/market/checkpoints/start0.json \
           storage/market/checkpoints/start1.json \
           storage/market/checkpoints/start2.json \
  --out storage/market/calibration_result.json
```

`combine` picks the best objective value, builds the degeneracy report
from all three starts, attaches the fit target moments, and adds the
252-day drawdown diagnostic. If a start is interrupted, rerun just that
`--start-index`; completed checkpoints are kept.

Validate on holdout (needs the raw bars directory with `<TICKER>_daily.csv`):

```bash
eve-miro market-calibrate validate \
  --result storage/market/calibration_result.json \
  --raw-dir /path/to/calibration/raw
```

## Compute budget

The calibration runner (`core/calibration/runner.py`) steps the archetypes
against the order book directly, skipping the full engine's per-step
overhead: about 0.5s per 126-day replication with 32 agents. One objective
evaluation (3 replications, fixed seeds) is about 1.5s. A full 3-start
search with threshold accepting is on the order of an hour on one CPU.
Final validation reruns use fresh seeds.

## Honest limits

- **Parameter degeneracy.** Platt and Gebbie showed that intraday
  agent-based models can reproduce stylized facts while leaving behavioral
  parameters unidentified. The CLI reports a degeneracy analysis across
  starting points: if objectives agree within 10 percent but parameters
  differ, the point estimate is not identified and the report says so.
  Do not quote calibrated parameters to spurious precision.
- **Daily-bar resolution.** The simulator steps hourly and emits daily
  closes; intraday microstructure (spreads, queue dynamics) is not
  calibrated. The Hawkes-process extension for noise-trader arrivals is
  the recommended follow-up for order-flow realism.
- **Baseline only.** MSM calibrates everyday market dynamics. Shock
  scenarios (sell shock, volatility spike, rate shock) are scored
  separately by the alignment module and trust ledger; calibration does
  not make any scenario class trustworthy by itself.
- **Regime change.** Parameters fitted on 2019-2023 encode that period's
  market structure. The holdout validation measures how well they
  transfer; a large fit-vs-holdout gap means the market changed, not that
  the fit was wrong.
- **What this is not.** Calibrated parameters do not predict returns,
  volatility, or prices. They make the simulator's *distributions*
  resemble history's, which is what scenario stress-testing needs.
