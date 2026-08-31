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
            fail closed if down        fail closed if unbuilt  + Trust Profile
            SIMULATED                  SIMULATED               vs WorldState(t1)
```

Default is `EVE_MIRO_ENGINES=in-tree`. Missing LLM keys, a down Flask
server, or an unbuilt EVE CLI raise `EngineNotConfigured` (API 503) —
never a silent stub. Pytest `conftest.py` forces `stub` so unit tests stay
offline and do not need keys or a node build.

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

**First-time clone — one command** (fabric + MiroFish backend deps + EVE CLI
build + env templates if missing):

```bash
cd eve-miro
make install
# equivalent: python3 scripts/bootstrap.py
# Windows PowerShell: .\scripts\install.ps1
```

`make install-dev` is pip-only (`pip install -e ".[dev]"`) for the offline
test suite.

Then:

```bash
python3 -m pytest -q
FIXTURES=1 python3 -m uvicorn eve_miro.api.main:app --port 8000
# dashboard: http://127.0.0.1:8000/
```

FastAPI app entry: `src/eve_miro/api/main.py` (`eve_miro.api.main:app`).
Layout folder `apps/api` is a pointer — see that README.

### In-tree engines (fail closed)

`POST /experiments/run` uses MiroFish + EVE. If they are not up, the API
returns **503** `{"error":"engine_not_configured","detail":...}` instead of
running the typhoon stub.

`make install` / `python3 scripts/bootstrap.py` already created `.venv`,
installed `.[all]` + MiroFish requirements, built the EVE CLI, and copied
`.env.example` -> `.env` and `mirofish/.env.example` -> `mirofish/.env`
when those files were missing (never overwritten, never invents API keys).
Bootstrap prefers **one** `.venv` at repo root. On Python 3.13+ it warns
(MiroFish historically wants <3.13) and uses `python3.12` to create the venv
when that interpreter is on PATH.

After install, boot the engines:

1. Python 3.12 venv for MiroFish (`requires-python <3.13`) — the repo-root
   `.venv` from bootstrap.
2. `mirofish/.env` (copied from the example if missing). This first run uses a
   local OpenAI-compatible GGUF server:
   `LLM_API_KEY=local`, `LLM_BASE_URL=http://127.0.0.1:8088/v1`,
   `LLM_MODEL_NAME=qwen2.5-0.5b-instruct`, plus `MIROFISH_MEMORY=local`
   (skips Zep Cloud; does **not** fake Zep). Local memory builds an on-disk
   graph under `mirofish/backend/uploads/local_graphs/`; it is not Zep Cloud.
   Weights path: `models/qwen2.5-0.5b-instruct-q4_k_m.gguf`
   (see `scripts/local_llm_server.py`).
3. `python mirofish/backend/run.py` listens on http://127.0.0.1:5001
4. EVE CLI: `eve/bin/eve.js` and `eve/dist/cli/main.js` from the bootstrap
   build. The adapter calls `eve trajectory --stdin`.
   There is no HTTP `POST /validate`.
5. `FIXTURES=1 EVE_MIRO_ENGINES=in-tree python3 -m uvicorn eve_miro.api.main:app --port 8000`
6. `POST /experiments/run` fails loudly if steps 3-4 are not up.

MiroFish Flask routes used (not invented `/api/predict`):
`/api/graph/ontology/generate` then `/api/graph/build` then poll
`/api/graph/task/<id>` then `/api/simulation/create` then
`/api/simulation/prepare` then POST `/api/simulation/prepare/status`
then `/api/simulation/start` then poll `/api/simulation/<id>/run-status`
then `/actions` and `/timeline`.

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
