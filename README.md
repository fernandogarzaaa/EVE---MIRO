# EVE-MIRO

**Reality-grounded loop + in-tree MiroFish (simulation) + in-tree EVE (experience).**

A continuously evaluated synthetic-world platform that grounds multi-agent
simulations in live and historical open data, models agent experience with the
in-tree EVE engine, and measures simulated futures against observed reality.

This is **not** an AI dashboard and **not** a clone of SIGINT / God's Eye View /
AEGIS / H.O.T-EARTH. The data fabric, adapters, and core are first-party.
MiroFish and EVE ship **in this repository** as first-party engine trees.

## Layout

```
eve-miro/          data fabric, world state, API, dashboard (MIT)
mirofish/          swarm simulation engine (AGPL-3.0, first-party)
eve/               experience validation engine (MIT, first-party)
```

See `NOTICE.md` for the license split. Combined distribution that includes
`mirofish/` is subject to AGPL-3.0 for that component.

## The loop

```
 Reality
   → Data fabric (providers, quality, provenance)
   → WorldState(t0)         # OBSERVED, cutoff-bounded
   → orchestration (ClosedLoop)
   → MiroWorldAdapter → MiroFish-shaped sim   # SIMULATED
   → trajectories → EVE (ExperienceEngine)
   → Reality Aligner vs WorldState(t1)
   → Reality Ledger + Trust Profile
   → experience graph (CANDIDATE→VALIDATED→REPLICATED|CONFLICTING)
```

```
 ┌─────────────┐   OBSERVED/FORECAST    ┌──────────────┐
 │ Open-Meteo  │────────┐               │ Event log    │  never mutated
 │ USGS  …     │        ├──────────────▶│ (append-only)│
 │ stubs       │────────┘               └──────┬───────┘
 └─────────────┘                               │ fold ≤ t0
                                               v
                                        WorldState(t0)
                                        information_cutoff = t0
                                               │
                                               v
                                      orchestration / ClosedLoop
                    ┌──────────────────────────┼──────────────────────────┐
                    v                          v                          v
            MiroFish (in-tree)         EVE (in-tree)           Reality Ledger
            stub until configured      stub until configured   + Trust Profile
            SIMULATED                  SIMULATED               vs WorldState(t1)
```

Runtime still uses stubs unless `EVE_MIRO_ENGINES=in-tree` and the engine
can actually start. Missing LLM keys or an unbuilt EVE CLI fall back with
notes such as `mirofish_in_tree_not_configured`. Tests do not need keys.

`MIROFISH_URL` / `EVE_URL` / `EVE_BIN` are optional overrides to a **running
local service** (including compose). They are not GitHub install URLs.
`EVE_BIN` defaults to the in-tree CLI entry when that file exists.

## First domain

Earth + mobility + weather + events, **Philippines** bbox roughly
`4.2N–21.2N, 116.5E–127E`. Default scenario: Metro Manila typhoon
`experiments/historical-replay/typhoon_manila_001.yaml`. Closed loop:
`experiments/typhoon/typhoon_manila_closed_loop.yaml`.

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

Python 3.12 is the intended combined runtime (MiroFish targets <3.13); fabric
tests may still run on 3.13. Tests do **not** need Docker, the network, LLM keys,
or a node build.

```bash
cd eve-miro
python3 -m pip install -e ".[dev]"
python3 -m pytest -q
FIXTURES=1 python3 -m uvicorn eve_miro.api.main:app --port 8000
# dashboard: http://127.0.0.1:8000/
```

FastAPI app entry: `src/eve_miro/api/main.py` (`eve_miro.api.main:app`).
Layout folder `apps/api` is a pointer — see that README.

### In-tree engines

Uvicorn serves the API. MiroFish: `python mirofish/backend/run.py` (needs its .env). EVE: `eve/bin/eve.js` after installing packages in `eve/`. Set EVE_MIRO_ENGINES=in-tree to prefer live engines; otherwise adapters keep using stubs.

One-click demo (same as the dashboard **Load demo** button):

```bash
curl -s -X POST localhost:8000/demo -H 'content-type: application/json' -d '{}'
```

Optional stack (Postgres/PostGIS, Redis, MinIO, API):

```bash
docker compose up --build
docker compose --profile streaming up      # Redpanda
docker compose --profile timeseries up     # same PostGIS postgres; Timescale is future
docker compose --profile engines up --build
# engines profile builds ./mirofish (HTTP 5001) and ./eve (CLI image).
# Wire the API with MIROFISH_URL=http://mirofish:5001
# EVE is CLI-only. Alternative: cd mirofish && docker compose up
```

No Kubernetes. Default `docker compose up` does **not** start Redpanda or the
engines.
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

`GET /` dashboard · `GET /health` · `GET /reliability` · `GET /trust-profile` ·
`GET /ledger` · `GET /metrics` · `POST /demo` · `POST /experiments/run` ·
`POST/GET /worlds` · ingest · snapshot · state · events ·
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

Must pass without Docker, network, LLM keys, or a node build. Coverage includes
provenance mixing, cutoff leakage, WorldState reconstruction, Open-Meteo/USGS
fixture normalize, MAE, API happy path, DuckDB parquet traces, counterfactual
labeling, in-tree engine presence.

## License

Root data fabric: MIT (`LICENSE`). MiroFish: AGPL-3.0 (`mirofish/LICENSE`).
EVE: MIT (`eve/LICENSE`). See `NOTICE.md` and `docs/model-card.md`.
