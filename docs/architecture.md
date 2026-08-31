# Architecture

EVE-MIRO is a reality-to-simulation feedback system, not an AI dashboard.

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
| `apps/api` | `src/eve_miro/api/main.py` |
| `apps/worker` | `src/eve_miro/worker/loop.py` |
| `apps/dashboard` | FastAPI-served `apps/dashboard/index.html` |
| `core/*` | `src/eve_miro/core/*` |
| `providers` | `src/eve_miro/providers/*` |
| `storage` | `src/eve_miro/storage/*` |
| `streaming` | `src/eve_miro/streaming/*` |

## Engines are interfaces

`SimulationEngine` and `ExperienceEngine` are protocols. v1 ships `StubSimulationEngine` and `StubExperienceEngine`. MiroFish and EVE are replaceable backends; they are not vendored.

## First domain

Earth + mobility + weather + events, bounded to the Philippines bbox
`(4.2N–21.2N, 116.5E–127E)`. Default example: Metro Manila typhoon scenario
`experiments/historical-replay/typhoon_manila_001.yaml`.
