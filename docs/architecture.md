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
                                      Reality check (SIMULATED vs OBSERVED)
                                                    |
                                                    v
                                      prediction error -> EVE again
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

## Engines are interfaces

`SimulationEngine` and `ExperienceEngine` are protocols. v1 ships `StubSimulationEngine` and `StubExperienceEngine`. MiroFish and EVE are replaceable backends; they are not vendored and must not be cloned into this repo.

Optional env (ignored until a core factory exists):

- `MIROFISH_URL` → https://github.com/fernandogarzaaa/MiroFish
- `EVE_URL` → https://github.com/fernandogarzaaa/experience-validation-engine

API helper `resolve_simulation_engine()` calls `get_simulation_engine()` when core adds it; otherwise the stub.

## Compose profiles

- default: postgres/PostGIS, redis, minio, api
- `--profile streaming`: Redpanda
- `--profile timeseries`: same PostGIS postgres (Timescale is future; do not replace the PostGIS image)

MinIO prefixes: `raw/` `normalized/` `derived/` `simulation/` `experiments/`.

## First domain

Earth + mobility + weather + events, bounded to the Philippines bbox
`(4.2N–21.2N, 116.5E–127E)`. Default example: Metro Manila typhoon scenario
`experiments/historical-replay/typhoon_manila_001.yaml`.

## Second domain

Finance (CoinGecko stub). Same loop, public ticks only.
