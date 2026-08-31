# Architecture

EVE-MIRO is a **reality-to-simulation feedback system**, not an AI dashboard
and not an OSINT globe.

```
 Reality (public feeds)
        |
        v
 Data fabric (providers + quality + provenance)
        |
        v
 Event log (append-only) ---- reconstruct ----> WorldState(t)
        |                                           |
        |                              information_cutoff = t
        v                                           v
 Historical replay / ingest              SimulationEngine (stub | MiroFish)
        |                                           |
        v                                           v
 OBSERVED events                          SIMULATED trajectories
                                                    |
                                                    v
                                      ExperienceEngine (stub | EVE)
                                                    |
                                                    v
                                      ValidatedExperience + counterfactuals
                                                    |
                                                    v
                                      Reality Aligner vs WorldState(t1)
                                                    |
                                                    v
                                      Reality Ledger + Trust Profile
                                                    |
                                                    v
                                      experience graph / EVE again
```

## Packages

Importable code lives in `src/eve_miro/` (`python path` package `eve_miro`).

| Layout folder | Implementation |
|---|---|
| `apps/api` | `src/eve_miro/api/main.py` + `routes_extra.py` |
| `apps/worker` | `src/eve_miro/worker/loop.py` |
| `apps/dashboard` | FastAPI-served `apps/dashboard/index.html` (keep in sync with `src/eve_miro/api/static/index.html`) |
| `core/*` | `src/eve_miro/core/*` |
| `providers` | `src/eve_miro/providers/*` |
| `storage` | `src/eve_miro/storage/*` |
| `streaming` | `src/eve_miro/streaming/*` |

## Dashboard

Five working views against FastAPI:

1. **World** — events, source, freshness, provenance badges, lat/lon list-map
2. **Simulation** — create/run `typhoon_manila_001`, status, population, cutoff, SIMULATED disclaimer
3. **Experience** — validated artifacts by layer (agent / population / simulator)
4. **Reality Check** — predicted vs observed sparkline, MAE/RMSE, “don’t trust this domain”
5. **Reliability** — per-source freshness/completeness/availability + simulation calibration

**Load demo** → `POST /demo` (world, Open-Meteo+USGS fixtures, snapshot, sim, evaluate).

## Engines are in-tree

`SimulationEngine` and `ExperienceEngine` are protocols. Default
`EVE_MIRO_ENGINES` is `in-tree` (fail closed: `EngineNotConfigured`, never a
silent stub). Pytest forces `stub`. Trees live at `mirofish/` and `eve/`.

`MIROFISH_URL` / `EVE_URL` / `EVE_BIN` override to a running local service
(including `docker compose --profile engines`). They are not GitHub install URLs.

API helper `resolve_simulation_engine()` calls `get_simulation_engine()`.

## Compose profiles

- default: postgres/PostGIS, redis, minio, api
- `--profile streaming`: Redpanda
- `--profile timeseries`: same PostGIS postgres (Timescale is future; do not replace the PostGIS image)
- `--profile engines`: in-tree MiroFish (HTTP 5001) and EVE (CLI image)

MinIO prefixes: `raw/` `normalized/` `derived/` `simulation/` `experiments/`.

## First domain

Earth + mobility + weather + events, bounded to the Philippines bbox
`(4.2N–21.2N, 116.5E–127E)`. Default example: Metro Manila typhoon scenario
`experiments/historical-replay/typhoon_manila_001.yaml`.

## Second domain

Finance (CoinGecko live + fixture). Same loop, public ticks only.
