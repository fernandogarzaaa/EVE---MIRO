# Market trust accumulation

`eve-miro market-accumulate` is the weekly job that keeps the market
scenario trust ledger honest. Every run grounds all three market
scenarios in the latest live market state, simulates them with the
Phase 5 calibrated archetype parameters, aligns each simulated path
against the most recent realized window, and appends one record per
scenario per ISO week to the trust ledger. The per-class trust summary
is recomputed from the full ledger file on every run.

## What one run does

1. **Ground.** Fetches live daily bars for SPY and AAPL via yfinance
   (fail closed when unavailable), the latest VIX close for context
   (soft-fail), a FRED macro snapshot when `FRED_API_KEY` is set (soft
   skip otherwise), and a GDELT market-news article count (soft skip on
   failure). A trailing bar dated today (UTC) is dropped so the realized
   window always ends on the latest complete bar.
2. **Simulate.** Runs `sell_shock_001`, `vol_spike_001`, and
   `rate_shock_001` through the marketsim engine over a 480-hour horizon
   (20 trading days), using the calibrated parameters from
   `storage/market/calibration_result.json` (Phase 5 best fit).
3. **Align.** Each simulated daily path is aligned against the trailing
   20 trading days with the Phase 3 alignment module: two-sample KS on
   log returns, rolling realized-vol path MAE, and max-drawdown depth
   error, aggregated to a score in [0, 1].
4. **Ledger.** Appends one JSON record per scenario to
   `storage/market/trust_ledger.jsonl`, keyed by ISO week
   (e.g. `2026-W40`). Recomputes `storage/market/trust_summary.json`
   from the whole ledger file (never from memory) and refreshes
   `storage/market/latest_market_run.json` so the dashboard Market tab
   shows the newest run with the ledger-wide trust table.

Idempotency: a week with all three scenario records already present
exits 0 with a skip message. A partially recorded week only runs the
missing scenarios. To re-run a week manually, pass `--week` with an
unrecorded label such as `2026-W40b`.

## Ledger schema

One JSON object per line in `trust_ledger.jsonl`:

- `week`: ISO week label, e.g. `2026-W40`
- `run_at`: UTC timestamp of the run
- `scenario`: scenario id, e.g. `sell_shock_001`
- `scenario_class`: `sell_shock`, `volatility_spike`, or `rate_shock`
- `tickers`: `["SPY", "AAPL"]`
- `hours`: simulated horizon (480)
- `n_bars`: realized bars aligned (20)
- `vix`: latest VIX close, or null when the fetch failed
- `macro`: FRED snapshot (`{series_id: {date, value}}`), or null
- `news`: `{"n_articles": N, "query": ...}`, or null
- `alignment`: `aggregate_score`, per-symbol metrics
  (`symbol_score`, `ks_statistic`, `vol_path_mae`, `drawdown_error`,
  `n_points`), `skipped_symbols`
- `data_source`: always `"live"` (fail closed: no bars, no record)

## Trust thresholds

Per-class trust comes from `scenario_trust_from_ledger` over the full
ledger: `score = 0.6 * (drawdown within 2% fraction) + 0.4 * (1 - mean
KS statistic)`. Recommendations use the existing thresholds:
below 0.40 is DO_NOT_USE, below 0.70 is CAUTION, otherwise USE.
With few alignments every class reads DO_NOT_USE; that is the honest
starting point, and scores move only as independent weekly alignments
accumulate.

## Running manually

From the repo root with the package installed:

```sh
eve-miro market-accumulate
```

Environment: no live flags are needed (the job fetches live data
directly and fails closed without it). Optional: `FRED_API_KEY` for the
macro snapshot. The job writes under `storage/market/` in the repo.

## Scheduler

Run weekly on Monday mornings Asia/Manila from the repo root:

```sh
cd /path/to/EVE---MIRO && eve-miro market-accumulate
```

with `FRED_API_KEY` exported when available. The job is idempotent per
ISO week, so overlapping or retried runs cannot duplicate records.

## Honest limits

- Trust measures scenario-class calibration against observed windows,
  not predictive power. A high score means the scenario behaved like
  past realizations, never that the simulator predicts prices.
- The realized window is one draw; exogenous news is unmodeled.
- Calibrated parameters carry the Phase 5 degeneracy caveat: several
  distinct parameter vectors fit the historical moments about equally
  well.
- The simulator under-produces fat tails and deep drawdowns relative to
  history (documented in `docs/market-calibration.md`); trust scores
  reflect that gap rather than hiding it.
