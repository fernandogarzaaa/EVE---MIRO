"""DuckDB analytics over simulation Parquet traces."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from eve_miro.config import REPO_ROOT, TRACES_DIR


def traces_glob(directory: Path | None = None) -> str:
    d = directory or TRACES_DIR
    d.mkdir(parents=True, exist_ok=True)
    return str(d / "*.parquet")


def query_traces(sql: str | None = None, *, directory: Path | None = None) -> list[dict[str, Any]]:
    """Run a DuckDB query over Parquet traces. Default: mean congestion by hour."""
    glob = traces_glob(directory)
    con = duckdb.connect(database=":memory:")
    default = f"""
        SELECT hour, avg(congestion) AS mean_congestion, count(*) AS n_rows,
               sum(CASE WHEN action = 'evacuate' THEN 1 ELSE 0 END) AS evacuate_n
        FROM read_parquet('{glob}')
        GROUP BY hour
        ORDER BY hour
    """
    q = sql or default
    try:
        rel = con.execute(q)
    except Exception:
        con.execute(f"CREATE VIEW traces AS SELECT * FROM read_parquet('{glob}')")
        rel = con.execute(q)
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, row)) for row in rel.fetchall()]


def write_trace_parquet(rows: list[dict[str, Any]], path: Path) -> Path:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(database=":memory:")
    if not rows:
        raise ValueError("no trace rows")
    # register via JSON for a simple schema-on-write
    tmp = path.with_suffix(".json")
    tmp.write_text(json.dumps(rows))
    con.execute(f"CREATE TABLE t AS SELECT * FROM read_json_auto('{tmp}')")
    con.execute(f"COPY t TO '{path}' (FORMAT PARQUET)")
    tmp.unlink(missing_ok=True)
    return path
