from pathlib import Path

from eve_miro.storage.analytics import query_traces, write_trace_parquet


def test_duckdb_parquet_trace_query(tmp_path: Path):
    rows = [
        {
            "simulation_id": "s1",
            "hour": 0,
            "t": "2026-08-31T10:00:00Z",
            "agent_id": "persona_0001",
            "action": "stay",
            "wind_speed": 20.0,
            "congestion": 0.1,
            "warning_active": False,
            "outcome": "remained",
            "provenance_kind": "simulated",
        },
        {
            "simulation_id": "s1",
            "hour": 6,
            "t": "2026-08-31T16:00:00Z",
            "agent_id": "persona_0002",
            "action": "evacuate",
            "wind_speed": 40.0,
            "congestion": 0.5,
            "warning_active": True,
            "outcome": "evacuated",
            "provenance_kind": "simulated",
        },
        {
            "simulation_id": "s1",
            "hour": 6,
            "t": "2026-08-31T16:00:00Z",
            "agent_id": "persona_0003",
            "action": "evacuate",
            "wind_speed": 40.0,
            "congestion": 0.5,
            "warning_active": True,
            "outcome": "evacuated",
            "provenance_kind": "simulated",
        },
    ]
    path = write_trace_parquet(rows, tmp_path / "s1.parquet")
    assert path.exists()
    out = query_traces(directory=tmp_path)
    assert out
    hour6 = next(r for r in out if r["hour"] == 6)
    assert hour6["evacuate_n"] == 2
    assert abs(hour6["mean_congestion"] - 0.5) < 1e-9
