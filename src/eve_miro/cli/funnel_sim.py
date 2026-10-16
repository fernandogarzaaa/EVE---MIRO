"""eve-miro funnel-sim: run a funnel scenario end-to-end, offline.

Grounds the run in the baseline fixture
(``datasets/fixtures/funnel_baseline.json``) with provenance labels, runs
the funnelsim scenario named by ``--scenario`` from ``experiments/funnel/``,
and writes the run summary to ``storage/funnel/latest_funnel_run.json`` for
the dashboard.

There is no observed t1 for funnel scenarios yet (no pilot data), so the
run is recorded to the ledger as projection-only (verdict PENDING) and
never fabricated into an alignment score. When pilot data exists, align
the predicted series against it and replace the projection record.

Everything simulated is labeled SIMULATED. This is scenario output, not a
forecast: it answers what a scenario implies under stated assumptions,
never what will happen.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from eve_miro.core.reality.ledger import RealityLedger
from eve_miro.core.world.state import Population, WorldState
from eve_miro.errors import EngineNotConfigured
from eve_miro.paths import REPO_ROOT


def list_scenarios() -> list[str]:
    """Scenario ids from experiments/funnel/*.yaml with type: funnel.

    The registry is the YAML directory, not a hardcoded tuple: adding a
    scenario file makes it runnable via the CLI. Unknown names fail closed
    at lookup time.
    """
    out: list[str] = []
    funnel_dir = REPO_ROOT / "experiments" / "funnel"
    if not funnel_dir.is_dir():
        return out
    for path in sorted(funnel_dir.glob("*.yaml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(doc, dict) and doc.get("type") == "funnel" and doc.get("name"):
            out.append(path.stem)
    return out


SCENARIOS = tuple(list_scenarios())
DEFAULT_MONTHS = 3
MIN_MONTHS = 1
SEEDS_OFFSET = 1

REQUIRED_FIXTURE_KEYS = (
    "baseline_review_share",
    "gatherup_conversion_per_100_requests",
    "text_cost_all_in",
    "provenance",
)


def fail(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 1


def summary_path() -> Path:
    return REPO_ROOT / "storage" / "funnel" / "latest_funnel_run.json"


def write_funnel_summary(summary: dict[str, Any]) -> Path:
    path = summary_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return path


def _load_fixture(fixture_dir: Path) -> dict[str, Any]:
    path = fixture_dir / "funnel_baseline.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"missing fixture {path} (run with the repo fixtures present; "
            "funnel-sim is offline-only and refuses to invent baseline data)"
        )
    doc = json.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED_FIXTURE_KEYS if k not in doc]
    if missing:
        raise EngineNotConfigured(f"funnel-sim: fixture {path} missing keys: {missing}")
    return doc


def _load_scenario_doc(name: str) -> dict[str, Any]:
    path = REPO_ROOT / "experiments" / "funnel" / f"{name}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"missing scenario definition {path}")
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"scenario {path} did not parse to a mapping")
    return doc


def _scenario_kwargs(doc: dict[str, Any], *, days: int, seed: int) -> dict[str, Any]:
    conditions = doc.get("conditions", {}) or {}
    return {
        "mode": conditions.get("mode", "post_job"),
        "simulated_days": days,
        "movers": int((doc.get("agents", {}) or {}).get("population", 3)),
        "random_seed": seed,
        "origin": doc.get("information_cutoff", "2026-10-01T00:00:00Z"),
        "jobs_per_month": conditions.get("jobs_per_month", 60.0),
        "contactable_coverage": conditions.get("contactable_coverage", 0.80),
        "review_conversion": conditions.get("review_conversion", 0.20),
        "opt_out_rate": conditions.get("opt_out_rate", 0.01),
        "problem_rate": conditions.get("problem_rate", 0.20),
        "problem_resolve_prob": conditions.get("problem_resolve_prob", 0.70),
        "office_response_days_mean": conditions.get("office_response_days_mean", 2.0),
        "leads_per_day": conditions.get("leads_per_day", 10.0),
        "pricing": conditions.get("pricing", {}),
        "interventions": doc.get("interventions", []),
    }


async def _run_scenario(
    scenario_name: str,
    months: int,
    fixture_dir: Path,
    *,
    experiment_id: str = "funnel-sim-cli",
) -> dict[str, Any]:
    """Run one funnel scenario and return the summary dict."""
    from funnelsim.engine import FunnelSimEngine
    from funnelsim.scenarios import funnel_scenario

    fixture = _load_fixture(fixture_dir)
    doc = _load_scenario_doc(scenario_name)
    days = months * 30
    cutoff = doc.get("information_cutoff", "2026-10-01T00:00:00Z")

    world = WorldState(
        world_id=f"funnel-sim-{scenario_name}",
        timestamp=cutoff,
        information_cutoff=cutoff,
    )

    base_seed = int(doc.get("random_seed", 20261016))
    seeds = [base_seed, base_seed + SEEDS_OFFSET]
    movers = int((doc.get("agents", {}) or {}).get("population", 3))

    series_runs: list[dict[str, list[float]]] = []
    summaries: list[dict[str, Any]] = []
    for seed in seeds:
        sc = funnel_scenario(scenario_name, **_scenario_kwargs(doc, days=days, seed=seed))
        engine = FunnelSimEngine(scenario=sc)
        sim = await engine.initialize(world, Population(synthetic_n=movers))
        until = sim.origin + timedelta(hours=days * 24)
        result = await engine.run(sim, until)
        series_runs.append({k: [float(v) for v in vals] for k, vals in result.predicted_series.items()})
        summaries.append(result.summary)

    # Mean across seeds, per day.
    keys = series_runs[0].keys()
    mean_series: dict[str, list[float]] = {}
    for k in keys:
        n = min(len(r[k]) for r in series_runs)
        mean_series[k] = [sum(r[k][i] for r in series_runs) / len(series_runs) for i in range(n)]

    def _mean(field: str) -> float:
        vals = [s[field] for s in summaries if isinstance(s.get(field), (int, float))]
        return sum(vals) / len(vals) if vals else 0.0

    ledger = RealityLedger()
    rec = ledger.record_prediction(
        experiment_id=experiment_id,
        scenario_id=scenario_name,
        scenario_class="funnel",
        model="funnelsim",
        seed=None,
        cutoff=cutoff,
        domain="funnel",
        predicted=mean_series.get("reviews_per_100", []),
        observed=[],
        notes="projection-only: no observed t1 exists yet; align against pilot data when available",
    )

    return {
        "scenario": scenario_name,
        "months": months,
        "days": days,
        "seeds": seeds,
        "movers": movers,
        "mode": summaries[0].get("mode"),
        "cutoff": cutoff,
        "fixture_provenance": fixture.get("provenance"),
        "mean_series": {k: [round(v, 4) for v in vals] for k, vals in mean_series.items()},
        "metrics": {
            "jobs": int(sum(s.get("jobs", 0) for s in summaries) / len(summaries)),
            "reviews_gained": _mean("reviews_gained"),
            "incremental_share_pp": _mean("incremental_share_pp"),
            "implied_total_share_pp": _mean("implied_total_share_pp"),
            "conversion": _mean("conversion"),
            "problems_routed": _mean("problems_routed"),
            "problems_resolved": _mean("problems_resolved"),
            "opt_out_rate": _mean("opt_out_rate"),
            "bookings": _mean("bookings"),
            "cost": _mean("cost"),
            "revenue": _mean("revenue"),
            "margin": _mean("margin"),
            "margin_pct": _mean("margin_pct"),
        },
        "ledger_record_id": rec.id,
        "ledger_verdict": rec.verdict,
        "disclaimer": (
            "SIMULATED. Scenario projection under stated assumptions, not a forecast. "
            "Recorded as projection-only until pilot data exists to align against."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def run_funnel_scenario(
    scenario: str,
    months: int,
    fixture_dir: Path | None = None,
) -> dict[str, Any]:
    """Run a funnel scenario end-to-end and return the run summary dict.

    Shared by the `eve-miro funnel-sim` CLI. Offline-only. Raises
    ValueError on bad input, FileNotFoundError on missing fixtures or
    scenario files, EngineNotConfigured when the scenario cannot be built.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r} (expected one of {', '.join(SCENARIOS)})")
    if months < MIN_MONTHS:
        raise ValueError(f"months must be at least {MIN_MONTHS}")
    fdir = fixture_dir or (REPO_ROOT / "datasets" / "fixtures")
    return asyncio.run(_run_scenario(scenario, months, fdir))


def cmd_funnel_sim(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eve-miro funnel-sim")
    parser.add_argument(
        "--scenario",
        choices=SCENARIOS,
        default=SCENARIOS[0] if SCENARIOS else None,
        help="funnel scenario from experiments/funnel/",
    )
    parser.add_argument(
        "--months",
        type=int,
        default=DEFAULT_MONTHS,
        help="simulated horizon in months of 30 days (default 3)",
    )
    parser.add_argument(
        "--fixture-dir",
        default=None,
        help="override fixture directory (default: <repo>/datasets/fixtures)",
    )
    args = parser.parse_args(argv if argv is not None else [])

    if not SCENARIOS:
        return fail("no funnel scenarios found in experiments/funnel/")
    if args.months < MIN_MONTHS:
        return fail(f"--months must be at least {MIN_MONTHS}")
    fixture_dir = (
        Path(args.fixture_dir).expanduser() if args.fixture_dir else REPO_ROOT / "datasets" / "fixtures"
    )

    try:
        summary = run_funnel_scenario(args.scenario, args.months, fixture_dir)
    except FileNotFoundError as exc:
        return fail(str(exc))
    except EngineNotConfigured as exc:
        return fail(str(exc))
    except ValueError as exc:
        return fail(str(exc))

    path = write_funnel_summary(summary)
    m = summary["metrics"]
    print(
        f"funnel-sim  scenario={summary['scenario']}  months={summary['months']}  "
        f"mode={summary['mode']}  movers={summary['movers']}"
    )
    print(f"cutoff={summary['cutoff']}  seeds={summary['seeds']}")
    print(
        f"jobs={m['jobs']}  reviews_gained={m['reviews_gained']:.1f}  "
        f"incremental_share_pp={m['incremental_share_pp']:.1f}  "
        f"implied_total_share_pp={m['implied_total_share_pp']:.1f}"
    )
    print(
        f"conversion={m['conversion']:.3f}  problems_routed={m['problems_routed']:.1f}  "
        f"problems_resolved={m['problems_resolved']:.1f}  opt_out_rate={m['opt_out_rate']:.3f}"
    )
    if m["bookings"]:
        print(f"bookings={m['bookings']:.1f}")
    print(
        f"cost=${m['cost']:.2f}  revenue=${m['revenue']:.2f}  "
        f"margin=${m['margin']:.2f} ({m['margin_pct']:.1f}%)"
    )
    print(f"ledger: {summary['ledger_record_id']} verdict={summary['ledger_verdict']} (projection-only)")
    print(f"summary written to {path}")
    print(summary["disclaimer"])
    return 0
