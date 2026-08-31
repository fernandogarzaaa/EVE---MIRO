"""Tiny live closed loop: WorldState -> MiroFish Flask -> EVE CLI -> ledger.

2 agents, 1 seed, 1 round, baseline scenario only. Fail closed. Not a stub.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("EVE_MIRO_ENGINES", "in-tree")
os.environ.setdefault("MIROFISH_URL", "http://127.0.0.1:5001")
os.environ.setdefault("MIROFISH_TIMEOUT_S", "3600")
os.environ.setdefault("MIROFISH_POLL_S", "2")
os.environ.setdefault("EVE_BIN", str(ROOT / "eve" / "bin" / "eve.js"))
os.environ.setdefault("PYTHONPATH", str(ROOT / "src"))

from eve_miro.core.orchestration.closed_loop import ClosedLoop, split_at_cutoff
from eve_miro.core.orchestration.experiment import load_experiment
from eve_miro.providers.common import load_fixture
from eve_miro.providers.weather import OpenMeteoProvider
from eve_miro.storage.event_store import InMemoryEventStore


async def main() -> None:
    spec = load_experiment("typhoon_manila_closed_loop")
    spec.experiment.scenarios = [s for s in spec.experiment.scenarios if s.id == "baseline"]
    events = OpenMeteoProvider(mode="archive").normalize(load_fixture("openmeteo_manila_archive.json"))
    t0, t1 = split_at_cutoff(events, spec.cutoff)
    if not t0 or not t1:
        raise SystemExit(f"fixture split empty t0={len(t0)} t1={len(t1)}")
    loop = ClosedLoop()
    result = await loop.run(
        spec,
        InMemoryEventStore(),
        t0,
        t1,
        agents=2,
        seeds=[1],
        horizon_hours=1,
        world_id="live_typhoon_1",
    )
    out_dir = ROOT / "data"
    out_dir.mkdir(exist_ok=True)
    payload = result.model_dump(mode="json")
    (out_dir / "live_loop_result.json").write_text(json.dumps(payload, indent=2)[:200000], encoding="utf-8")
    print("engines", result.engines)
    print("seed_runs", len(result.seed_runs))
    for row in result.seed_runs:
        print(
            "run",
            row.scenario_id,
            "seed",
            row.seed,
            "sim",
            row.simulation_id,
            "summary",
            {k: row.summary.get(k) for k in ("engine", "project_id", "graph_id", "mirofish_simulation_id", "rounds", "actions_n", "posts")},
        )
    print(
        "alignments",
        [(a.metric_name, a.mae) for a in result.alignments],
    )
    print("ledger_n", len(result.ledger_record_ids))
    print("disclaimer", result.disclaimer[:80])


if __name__ == "__main__":
    asyncio.run(main())
