# EVE-MIRO

**Reality-grounded loop + in-tree MiroFish (simulation) + in-tree EVE (experience).**

A continuously evaluated synthetic-world platform that grounds multi-agent
simulations in live and historical open data, models agent experience with the
in-tree EVE engine, and measures simulated futures against observed reality.

This is **not** an AI dashboard and **not** a clone of SIGINT / God's Eye View /
AEGIS / H.O.T-EARTH. The data fabric, adapters, and core are first-party.
MiroFish and EVE ship **in this repository** as first-party engine trees.

## Status

Architecture, fail-closed in-tree engines, and a first live closed loop are on
`main`. This is **not** a finished product.

What has actually run end to end:

- WorldState(t0) from the Open-Meteo Manila archive fixture
- MiroFish Flask: ontology generate, on-disk local graph
  (`MIROFISH_MEMORY=local`), OASIS twitter
- EVE CLI `node eve/bin/eve.js trajectory --stdin` (no `POST /validate`)
- Reality ledger + trust profile

A 1-round slice at simulated hour 0 is OASIS off-peak, so `actions_n` can be
0. MiroFish social output does not currently map onto `wind_speed_10m`, so
weather MAE can be empty. That is a mapping gap, not a silent stub.

Still open: peak-hour / multi-round OASIS so agents actually post, and mapping
social timeline onto weather and mobility for alignment. OASIS stays on a
split Python 3.11 venv (`mirofish/.venv`); it cannot install on 3.12+. Several
providers remain stubs.

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
`EVE_BIN` defaults to the in-tree CLI entry when that file exists. A `.js`
path is launched with `node` (Windows cannot exec `eve.js` directly).

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

```bash
curl -fsSL https://raw.githubusercontent.com/fernandogarzaaa/EVE---MIRO/main/install.sh | bash
```

```powershell
iex (irm https://raw.githubusercontent.com/fernandogarzaaa/EVE---MIRO/main/install.ps1)
```

That clones this repo to `~/.eve-miro/src` (Windows `%USERPROFILE%\.eve-miro\src`),
creates the fabric venv + EVE CLI build, installs a PATH shim (`eve-miro`), and
installs OASIS into `mirofish/.venv` **when Python 3.11 is on PATH**. Piped
installs stay non-interactive (no TTY prompts, no invented API keys). Then:

```bash
eve-miro           # help
eve-miro setup     # LLM keys (--provider ollama|openai|grok|deepseek|openrouter|azure|custom)
eve-miro doctor    # 3.11 OASIS import, node, eve.js (flask/ollama optional)
eve-miro serve     # MiroFish Flask :5001
eve-miro run       # tiny live loop, fail closed
eve-miro api       # uvicorn eve_miro.api.main:app :8000
```

Python versions are split on purpose — this is not a single venv:

- Fabric (this API, tests, closed loop, `eve-miro` CLI): Python **3.12+** at
  `<src>/.venv`. 3.13 is fine for tests.
- MiroFish OASIS (`camel-oasis==0.2.5`): Python **3.10 or 3.11 only**. It will
  **not** install on 3.12+. Use `mirofish/.venv` on 3.11 for Flask. Pin
  `mcp>=1.6,<2` so camel-ai 0.2.78 can import `FastMCP`. If the installer only
  finds one Python, it uses it for fabric and **warns** that OASIS needs 3.11.

Tests do **not** need Docker, the network, LLM keys, OASIS, or a node build.

**Already cloned — fabric + EVE CLI:**

```bash
cd eve-miro
make install
# equivalent: python3 scripts/bootstrap.py
# Windows PowerShell: .\scripts\install.ps1
```

`make install` still works. It creates the repo-root `.venv` (3.12+), builds
the EVE CLI, copies env examples only when missing, and creates
`mirofish/.venv` when `python3.11` exists. `make install-dev` is pip-only
(`pip install -e ".[dev]"`) for the offline test suite.

Then:

```bash
python3 -m pytest -q
eve-miro api
# or: FIXTURES=1 python3 -m uvicorn eve_miro.api.main:app --port 8000
# dashboard: http://127.0.0.1:8000/
```

FastAPI app entry: `src/eve_miro/api/main.py` (`eve_miro.api.main:app`).
Layout folder `apps/api` is a pointer — see that README.

### In-tree engines (fail closed)

`POST /experiments/run` uses MiroFish + EVE. If they are not up, the API
returns **503** `{"error":"engine_not_configured","detail":...}` instead of
running the typhoon stub.

The one-liner and `make install` / `python3 scripts/bootstrap.py` copy
`.env.example` -> `.env` and `mirofish/.env.example` -> `mirofish/.env`
only when those files were missing (never overwritten, never invents API keys).
Fabric lives in repo-root `.venv` on 3.12+. OASIS is a **second** venv at
`mirofish/.venv` on 3.11 (`pip install -r mirofish/backend/requirements.txt`).
If 3.11 is missing, that step is skipped with a warning — Flask/OASIS will not
run until you add 3.11.

After install, boot the engines:

1. **LLM.** GPU path (NVIDIA, recommended): Ollama with `qwen2.5:3b` on CUDA.
   `mirofish/.env`:
   `LLM_API_KEY=local`, `LLM_BASE_URL=http://127.0.0.1:11434/v1`,
   `LLM_MODEL_NAME=qwen2.5:3b`, `MIROFISH_MEMORY=local`.
   CPU path: local GGUF server at `http://127.0.0.1:8088/v1`,
   `LLM_MODEL_NAME=qwen2.5-0.5b-instruct`, weights
   `models/qwen2.5-0.5b-instruct-q4_k_m.gguf`
   (see `scripts/local_llm_server.py`). Dummy key `local` is only for a
   local OpenAI-compatible endpoint.
2. **Memory.** `MIROFISH_MEMORY=local` skips Zep Cloud and builds a real
   JSON graph under `mirofish/backend/uploads/local_graphs/`. It is not
   Zep Cloud and not a stub. Missing ZEP with local memory **off** still
   fail-closes (HTTP 500).
3. **MiroFish Flask** (`eve-miro serve`) from the 3.11 venv:
   `mirofish/.venv/Scripts/python.exe mirofish/backend/run.py` (Windows)
   or `mirofish/.venv/bin/python mirofish/backend/run.py`.
   Listens on http://127.0.0.1:5001
4. **EVE CLI:** `eve/bin/eve.js` and `eve/dist/cli/main.js` from the
   bootstrap build. The adapter calls `node eve/bin/eve.js trajectory --stdin`.
   There is no HTTP `POST /validate`.
5. Fabric API: `eve-miro api`
   (`FIXTURES=1 EVE_MIRO_ENGINES=in-tree python3 -m uvicorn eve_miro.api.main:app --port 8000`)
6. Tiny live closed loop (needs steps 1–4): `eve-miro run`

```bash
export EVE_MIRO_ENGINES=in-tree
export MIROFISH_URL=http://127.0.0.1:5001
export MIROFISH_TIMEOUT_S=3600
export MIROFISH_MEMORY=local
python scripts/run_live_tiny_loop.py
```

Writes `data/live_loop_result.json` (gitignored). 1 seed, 1 simulated hour,
baseline scenario only. Truncated OASIS runs pass `--no-wait` so the worker
exits instead of sitting in interview mode.

`POST /experiments/run` fails loudly if Flask or the EVE CLI is not up.

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
labeling, in-tree engine presence, local-graph memory, EVE `.js` launched via
`node`.

## License

Root data fabric: MIT (`LICENSE`). MiroFish: AGPL-3.0 (`mirofish/LICENSE`).
EVE: MIT (`eve/LICENSE`). See `NOTICE.md` and `docs/model-card.md`.
