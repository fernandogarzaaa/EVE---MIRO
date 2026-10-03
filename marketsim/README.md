# MarketSim

A purpose-built market simulation engine (MIT, first-party). It grounds
agent-based market scenarios in observed `WorldState` data and produces
SIMULATED price trajectories for strategy stress-testing. It is not a
price forecasting model.

## Layout

```
marketsim/
  orderbook.py   limit order book, price-time priority, deterministic
  agents.py      trader archetypes (market maker, momentum, noise, fundamental)
  engine.py      MarketSimEngine behind the SimulationEngine protocol
  scenarios.py   programmatic Scenario builder (canonical YAML in experiments/market/)
```

`marketsim` never imports from `mirofish/` (AGPL-3.0). It only depends on
the MIT data fabric (`eve_miro.*`) for the `SimulationEngine` protocol and
world models.

## How a run works

1. `MarketSimEngine.initialize(world, population)` reads the market slice
   at `WorldState` `Economy.indicators["market_snapshot"]["tickers"]`
   (ticker -> latest close, realized vol windows) via `read_market_slice()`. When that slice is absent, the
   Scenario's `conditions.symbols` and `conditions.initial_prices` supply
   the instruments instead. With neither, it raises `EngineNotConfigured`
   (fail closed, never a silent stub).
2. Each step: shock interventions due at that hour apply first, then every
   agent decides orders from a view that only contains history up to the
   current step (no lookahead), orders match in per-instrument books, and
   mids/spreads/volumes are recorded.
3. `run()` finalizes a `SimulationResult` with per-symbol price series,
   per-symbol return / max drawdown / volume, and agent traces. The first
   element of each internal mid history is the observed seed price; every
   element of `predicted_series` is SIMULATED.

## Trader archetypes

- **Market maker**: quotes both sides around mid, spread in bps, and skews
  quotes against inventory (long inventory shades quotes down). Refreshes
  quotes every step; respects an inventory limit.
- **Momentum**: buys (sells) when the trailing return over a lookback
  exceeds a threshold, via market orders.
- **Noise**: uninformed random flow with small size. Its size scales with
  `vol_multiplier`, which is how volatility-spike interventions bite.
- **Fundamental**: mean-reverts toward a scenario-given fair value with a
  tolerance band. Rate-shock interventions shift fair values.

## Interventions

| type | extra fields | effect |
|---|---|---|
| `sell_shock` | `symbol`, `quantity`, `duration_hours` (default 1) | large uninformed seller; with duration > 1 a persistent liquidator works the order over that many hours |
| `volatility_spike` | `symbol`, `multiplier`, `duration_hours` | scales noise-trader size |
| `rate_shock` | `fair_value_pct_change`, `symbols` (optional) | reprices fundamental anchors |

Scenario YAMLs live in `experiments/market/`: `sell_shock_001`,
`vol_spike_001`, `rate_shock_001`. The engine factory
(`get_simulation_engine`) routes `scenario.type == "market"` to
MarketSimEngine when engines are in-tree; stub mode and all other
scenarios are unchanged.

## Honest limitations

- **Calibration trap.** Archetype parameters (spreads, thresholds, sizes)
  are assumptions, not estimates. Tuning them to reproduce past prices is
  overfitting one level up; the trust ledger is where that gets measured.
- **No exogenous news.** The future contains surprises that are not in past
  data. Shocks must be specified as interventions; the sim cannot generate
  them on its own.
- **Stationary behavior.** Agent rules are fixed for a run. Real markets are
  adversarial and adaptive; participants change strategies in response to
  each other.
- **Not a forecast.** Output is distributions of outcomes under stated
  scenarios (for example, the 5th-percentile drawdown under a sell shock),
  never "the price will be X".
