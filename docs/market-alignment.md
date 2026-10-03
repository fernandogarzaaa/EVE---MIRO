# Market Alignment

How EVE-MIRO scores simulated market trajectories against observed reality,
and how calibration is tracked per scenario class.

## What alignment measures

After a marketsim run, the closed loop compares each simulated per-symbol
price path against the OBSERVED `market.bar` close series over the same
horizon (WorldState t1). Three metrics per ticker:

1. **Return-distribution comparison** — two-sample Kolmogorov-Smirnov test
   on log returns. Answers: does the sim produce the same *shape* of
   returns as the realized path, regardless of timing?
2. **Realized-vol path comparison** — MAE between rolling annualized
   realized-vol series (simulated vs observed). Answers: does the sim get
   the *volatility regime* right through the horizon?
3. **Max-drawdown depth comparison** — absolute difference between the
   simulated and observed worst peak-to-trough loss. Answers: does the
   scenario stress the book as hard as reality did?

Each ticker gets a `symbol_score` in [0, 1] (mean of the three component
scores, each mapped so 1.0 is perfect), and the scenario gets an
`aggregate_score` (mean over tickers). Identical series score exactly 1.0.

## Scenario-class trust

Calibration is tracked per scenario class, not per scenario id:

- `sell_shock`
- `volatility_spike`
- `rate_shock`
- `baseline` (anything else)

Every market ledger record carries its `scenario_class` plus the metric
values. `scenario_trust_from_ledger` answers the calibration question
directly:

> For scenario class X, over N past alignments, the sim's drawdown
> predictions were within Y of observed Z% of the time.

The trust score blends that hit-rate (60%) with the mean KS statistic
(40%) and maps to USE / CAUTION / DO_NOT_USE at the same thresholds as
domain trust. Classes with no alignments are DO_NOT_USE, loudly.

## Reading a trust profile

- A high score for `sell_shock` means: when we ran liquidation-shock
  scenarios before, the simulated drawdowns usually landed near what
  actually happened. It does **not** mean the next shock is predicted.
- A low score means the scenario class is miscalibrated: widen the
  shock parameters, add archetypes, or stop quoting its numbers.
- Trust is computed from ledger records, never from an LLM or a
  narrative. The ledger is append-only; history is never rewritten.

## Honest limitations

- Alignment is scored against **one realized path**. A single draw cannot
  validate a distribution; it can only fail to falsify it.
- **Exogenous news is unmodeled.** If the realized path was driven by a
  surprise the sim cannot generate, the score punishes the sim for the
  world's randomness, not for a modeling error. Read low scores with
  that in mind.
- The MAE verdict threshold on ledger records is 2% of the mean observed
  price per ticker. It is a convention for the CORRECT / INCORRECT label,
  not a statement about economic significance.
- The KS p-value uses the asymptotic Kolmogorov distribution and is
  approximate for short horizons.

## Where it lives

- Metrics: `src/eve_miro/core/orchestration/market_alignment.py`
- Ledger fields (`scenario_class`, `metrics`): `src/eve_miro/core/reality/ledger.py`
- Per-class trust: `scenario_trust_from_ledger` in
  `src/eve_miro/core/reality/trust_profile.py`
- Closed-loop wiring: `src/eve_miro/core/orchestration/closed_loop.py`
  (market branch runs when the experiment declares
  `simulation.engine: marketsim`)
- Tests: `tests/test_market_alignment.py`
