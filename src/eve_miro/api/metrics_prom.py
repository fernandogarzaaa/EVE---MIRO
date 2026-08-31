"""In-process counters. Prometheus text when possible; JSON otherwise.

No prometheus_client dependency — scrape GET /metrics as text/plain.
"""

from __future__ import annotations

from threading import Lock
from typing import Any

_lock = Lock()
_counters: dict[str, int] = {
    "ingest_count": 0,
    "sim_runs": 0,
    "evals": 0,
}


def inc_ingest(n: int = 1) -> None:
    with _lock:
        _counters["ingest_count"] += int(n)


def inc_sim_run(n: int = 1) -> None:
    with _lock:
        _counters["sim_runs"] += int(n)


def inc_eval(n: int = 1) -> None:
    with _lock:
        _counters["evals"] += int(n)


def snapshot() -> dict[str, int]:
    with _lock:
        return dict(_counters)


def reset_metrics() -> None:
    with _lock:
        for k in _counters:
            _counters[k] = 0


def render_prometheus() -> str:
    snap = snapshot()
    lines = [
        "# HELP eve_miro_ingest_count World events accepted by ingest.",
        "# TYPE eve_miro_ingest_count counter",
        f"eve_miro_ingest_count {snap['ingest_count']}",
        "# HELP eve_miro_sim_runs Simulation runs completed.",
        "# TYPE eve_miro_sim_runs counter",
        f"eve_miro_sim_runs {snap['sim_runs']}",
        "# HELP eve_miro_evals Reality-check evaluations persisted.",
        "# TYPE eve_miro_evals counter",
        f"eve_miro_evals {snap['evals']}",
        "",
    ]
    return "\n".join(lines)


def as_json() -> dict[str, Any]:
    return snapshot()
