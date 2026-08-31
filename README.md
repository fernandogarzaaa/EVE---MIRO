# EVE-MIRO

**Reality-to-simulation feedback system.**

A continuously evaluated synthetic-world platform that grounds multi-agent
simulations in live and historical open data, models agent experience with EVE
(behind an interface), and measures simulated futures against observed reality.

This is **not** an AI dashboard and **not** a clone of SIGINT / God’s Eye View /
AEGIS / H.O.T-EARTH / MiroFish. Adapters and core are first-party.
**MiroFish and EVE are replaceable engine interfaces; v1 ships stubs.**
Do not clone those repos into this tree.

## The loop

```
 Reality
   → Data fabric (providers, quality, provenance)
   → WorldState(t)          # reconstructed from an append-only event log
   → Simulation             # SIMULATED, cutoff-bounded
   → EVE experience/validation
   → Future scenarios
   → Reality check          # SIMULATED vs OBSERVED
   → prediction error
   → EVE again
```

```
 ┌─────────────┐   OBSERVED/FORECAST    ┌──────────────┐
 │ Open-Meteo  │────────┐               │ Event log    │  never mutated
 │ USGS  …     │        ├──────────────▶│ (append-only)│
 │ stubs       │────────┘               └──────┬───────┘
 └─────────────┘                               │ fold ≤ t
                                               v
                                        WorldState(t)
                                        information_cutoff = t
                                               │
                    ┌──────────────────────────┼──────────────────────────┐
                    v                          v                          v
            StubSimulationEngine     StubExperienceEngine          Reality check
            (MiroFish-shaped)        (EVE-shaped)                  MAE RMSE Brier
            SIMULATED                SIMULATED                     vs OBSERVED
```

Optional live engines (not vendored):

| env | points at | used as |
|---|---|---|
| `MIROFISH_URL` | https://github.com/fernandogarzaaa/MiroFish | `SimulationEngine` adapter |
| `EVE_URL` | https://github.com/fernandogarzaaa/experience-validation-engine | `ExperienceEngine` adapter |

v1 ignores these unless core later exposes `get_simulation_engine()`; the
API factory falls back to `StubSimulationEngine`.

## First domain

Earth + mobility + weather + events, **Philippines** bbox roughly
`4.2N–21.2N, 116.5E–127E`. Default scenario: Metro Manila typhoon
`experiments/historical-replay/typhoon_manila_001.yaml`.

## Second domain

**Finance** (stub): CoinGecko-style public market ticks. Same provenance
rules — public data only, no person tracking. Not the default Load demo.

## Provenance (mandatory, never mixed)

| Kind | Use |
|---|---|
| **OBSERVED** | Public measurements (Open-Meteo archive, USGS FDSN, …) |
| **DERIVED** | Folded WorldState and quality flags |
| **FORECAST** | Issued forecasts (Open-Meteo forecast endpoint) |
| **SIMULATED** | Engine output, experiences, counterfactuals |

Ingesting simulated data as observed **fails**. Tests cover this.

## No future leakage

Every `WorldState` and every simulation has `information_cutoff`.
Historical replay refuses any event after the cutoff.

## Public-data governance

- Public feeds only.
- Synthetic agents are **statistical personas, never a named real person**.
- No person tracking or profiling.
- Counterfactuals are labeled **model-generated, not fact**.
- The dashboard is a Reality Check, not an OSINT globe.

## How to run

Python 3.12+ (3.13 works). Tests do **not** need Docker or the network.

```bash
cd eve-miro
python3 -m pip install -e ".[dev]"
python3 -m pytest -q
FIXTURES=1 python3 -m uvicorn eve_miro.api.main:app --port 8000
# dashboard: http://127.0.0.1:8000/
```

FastAPI app entry: `src/eve_miro/api/main.py` (`eve_miro.api.main:app`).
Layout folder `apps/api` is a pointer — see that README.

One-click demo (same as the dashboard **Load demo** button):

```bash
curl -s -X POST localhost:8000/demo -H 'content-type: application/json' -d '{}'
```

Optional stack (Postgres/PostGIS, Redis, MinIO, API):

```bash
docker compose up --build
docker compose --profile streaming up      # Redpanda
docker compose --profile timeseries up     # same PostGIS postgres; Timescale is future
```

No Kubernetes. Default `docker compose up` does **not** start Redpanda.
Time series stay on PostGIS; do not swap that image for Timescale.

MinIO bucket prefixes: `raw/` `normalized/` `derived/` `simulation/` `experiments/`.

### Provider cadence

Do not poll everything every second.

| Provider | Interval | v1 |
|---|---|---|
| openmeteo | 1 h | live + fixture (archive=OBSERVED, forecast=FORECAST) |
| usgs | 15 min | live + fixture (OBSERVED) |
| opensky / aisstream | 30 s | stub |
| gdacs | 10 min | stub |
| gdelt | 15 min | stub |
| nasa / celestrak | 6 h | stub |
| osm | 24 h | stub |
| coingecko | 5 min | stub (finance domain) |
| worldbank | 30 d | stub |

Stubs report `health.available=false` unless `FIXTURES=1`.

## API

`GET /` dashboard · `GET /health` · `GET /reliability` · `GET /metrics` ·
`POST /demo` · `POST/GET /worlds` · ingest · snapshot · state · events ·
`POST/GET /simulations` · run · pause · resume · actions · outcomes ·
`GET/POST /experiences` · validate · `POST /scenarios` ·
`POST /scenarios/{id}/simulate` · `GET /evaluations/{id}` ·
`GET /provenance/{id}` (event→source walk when a graph exists).

The dashboard has five tabs that hit these routes: **World**, **Simulation**,
**Experience**, **Reality Check**, **Reliability**. Every record is labeled
**OBSERVED** or **SIMULATED** (and forecast/derived when applicable).

## Tests

```bash
python3 -m pytest -q
```

Must pass without Docker. Coverage includes provenance mixing, cutoff leakage,
WorldState reconstruction, Open-Meteo/USGS fixture normalize, MAE, API happy
path, DuckDB parquet traces, counterfactual labeling.

## License

MIT. See `LICENSE` and `docs/model-card.md`.
