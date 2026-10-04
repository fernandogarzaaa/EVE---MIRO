# MiroFish Simulations

Standalone OASIS social-media simulation scripts, intentionally decoupled
from `mirofish/backend`.

## Why a separate package?

The simulation scripts need `camel-oasis==0.2.5`, whose exact transitive pins
(`sentence-transformers==3.0.0`, `unstructured==0.13.7`, `camel-ai==0.2.78`)
carry known CVEs that cannot be fixed by bumping (0.2.5 is the latest
camel-oasis release). Keeping them here isolates that risk: the Flask backend
(`mirofish/backend`) no longer depends on them at all.

## Layout

- `run_twitter_simulation.py` — Twitter/X simulation preset
- `run_reddit_simulation.py` — Reddit simulation preset
- `run_parallel_simulation.py` — parallel dual-platform simulation
- `action_logger.py` — shared action logging helpers (stdlib only)

## Setup

```bash
cd mirofish/simulations
uv sync            # creates .venv with camel-oasis and friends
uv run python run_twitter_simulation.py --config /path/to/simulation_config.json
```

The backend's `SimulationRunner` launches these scripts with this package's
interpreter (`mirofish/simulations/.venv/bin/python`) when it exists,
falling back to its own interpreter otherwise.

Configuration is read from `mirofish/.env` (e.g. `LLM_API_KEY`).
