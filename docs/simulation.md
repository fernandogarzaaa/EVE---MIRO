# Simulation

`StubSimulationEngine` is a tiny Philippines typhoon-style run:

- Synthetic statistical personas (not real people; public demographic rates only)
- Seeded RNG
- Interventions from scenario YAML (e.g. `evacuation_warning` at +6h, coverage 0.8)
- Agent actions `stay | evacuate | shelter | stuck` with congestion
- Learning artifacts `{experience, conditions, confidence, source}`: if a
  warning-delay artifact has `confidence > 0.8`, the stub reduces cascade
- All outputs labeled SIMULATED

Population: 200 in tests, 1000 in `typhoon_manila_001` (not 10k).

A second world, not a second product: `type: market` (see
`experiments/historical-replay/market_ph_001.yaml`) runs a tiny investor
population reacting to ingested CoinGecko-like `market.price` events. Investors
are statistical personas, never real people. Simulated price paths stay SIMULATED;
OBSERVED prices live on `WorldState.economy`.

Historical replay (`core/simulation/replay.py`) refuses any event after
`information_cutoff`. Haiyan-style example:
`experiments/historical-replay/haiyan_cutoff_example.yaml` (cutoff
`2013-11-07T12:00:00Z` must reject a `2013-11-08` event).

## Engines are replaceable

`get_simulation_engine()` in `core/simulation/engine.py`:

- **v1 default:** `StubSimulationEngine` (no network)
- **`MIROFISH_URL` set:** `MiroFishEngine` POSTs `{seed, requirement, cutoff}` to
  `{MIROFISH_URL}/api/predict` (then `/simulate`). Timeout is short. On error it
  falls back to the stub and records provenance notes `mirofish_unavailable`.

MiroFish is not vendored. The adapter is a conservative HTTP client; the upstream
repo stays replaceable. Leave `MIROFISH_URL` unset unless you attach a live
service.
