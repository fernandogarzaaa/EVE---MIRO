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

## Engines are in-tree (fail closed)

`get_simulation_engine()` returns `StubSimulationEngine` only when
`EVE_MIRO_ENGINES=stub` (pytest). Otherwise it returns `MiroFishEngine`, which
talks to the real Flask app (`MIROFISH_URL`, default http://127.0.0.1:5001)
via `mirofish_client`:

1. POST `/api/graph/ontology/generate` (multipart seed `.md` + `simulation_requirement`)
2. POST `/api/graph/build` `{project_id}`
3. poll GET `/api/graph/task/<task_id>`
4. POST `/api/simulation/create` `{project_id, enable_twitter, enable_reddit}`
5. POST `/api/simulation/prepare` `{simulation_id}`
6. poll POST `/api/simulation/prepare/status`
7. POST `/api/simulation/start` `{simulation_id, max_rounds, platform}`
8. poll GET `/api/simulation/<id>/run-status`
9. GET `/api/simulation/<id>/actions` and `/timeline`

Missing `LLM_API_KEY`, missing Zep (unless `MIROFISH_MEMORY=local` /
`EVE_MIRO_ALLOW_LOCAL_MEMORY=1`), or a down server raises
`EngineNotConfigured`. There is no silent stub and no `/api/predict`.
Outputs are SIMULATED.
