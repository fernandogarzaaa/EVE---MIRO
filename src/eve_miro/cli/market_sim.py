"""eve-miro market-sim: run a market scenario end-to-end, offline.

Grounds WorldState(t0) from the Phase 1 fixture bars
(``datasets/fixtures/markets_bars.json``), runs the marketsim scenario named
by ``--scenario`` from ``experiments/market/``, aligns the simulated daily
paths against a held-out fixture window (the observed t1), records the
alignment to a fresh ledger, and prints the per-scenario-class trust
summary. Writes the run summary to
``storage/market/latest_market_run.json`` for the dashboard Market tab.

Everything simulated is labeled SIMULATED. This is calibration output,
not a forecast: it answers how well a scenario class reproduced one
realized window, never what prices will do next.
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

from eve_miro.core.orchestration.market_alignment import (
    observed_price_series,
    record_market_alignment,
)
from eve_miro.core.reality.ledger import RealityLedger
from eve_miro.core.reality.trust_profile import scenario_trust_from_ledger
from eve_miro.core.world.events import (
    Location,
    Provenance,
    ProvenanceKind,
    Source,
    Temporal,
    WorldEvent,
)
from eve_miro.core.world.markets import build_market_snapshot
from eve_miro.core.world.state import Economy, Population, WorldState
from eve_miro.errors import EngineNotConfigured
from eve_miro.paths import REPO_ROOT

SCENARIOS = ("sell_shock_001", "vol_spike_001", "rate_shock_001")
DEFAULT_HOURS = 120
DEFAULT_SEEDS_OFFSET = 1
MIN_HOURS = 72


def fail(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 1


def summary_path() -> Path:
    from eve_miro.paths import REPO_ROOT

    return REPO_ROOT / "storage" / "market" / "latest_market_run.json"


def write_market_summary(summary: dict[str, Any]) -> Path:
    path = summary_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return path


def _load_fixture_bars(fixture_dir: Path) -> list[dict[str, Any]]:
    path = fixture_dir / "markets_bars.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"missing fixture {path} (run with the repo fixtures present; "
            "market-sim is offline-only and refuses to invent market data)"
        )
    doc = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for series in doc.get("series", []):
        ticker = series.get("ticker")
        if not ticker:
            continue
        for bar in series.get("bars", []):
            close = bar.get("close")
            date = bar.get("date")
            if not isinstance(close, (int, float)) or not date:
                continue
            rows.append(
                {
                    "ticker": str(ticker),
                    "close": float(close),
                    "date": date,
                }
            )
    return rows


def _bar_event(idx: int, ticker: str, close: float, ts: datetime) -> WorldEvent:
    return WorldEvent(
        id=f"market-sim-bar-{ticker}-{idx}",
        source=Source(
            provider="markets_bars_fixture",
            dataset="markets_bars.json",
            license="fixture",
        ),
        observed_at=ts,
        ingested_at=ts,
        location=Location(lat=0.0, lon=0.0),
        event_type="market.bar",
        payload={"ticker": ticker, "close": close, "interval": "1d"},
        provenance=Provenance(kind=ProvenanceKind.OBSERVED, raw=True, confidence=0.9),
        temporal=Temporal(
            source_time=ts,
            effective_time=ts,
            valid_from=ts,
            valid_until=None,
            resolution="daily",
        ),
        information_cutoff=ts,
    )


def _parse_ts(raw: str) -> datetime:
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc)


def _load_scenario_doc(name: str) -> dict[str, Any]:
    path = REPO_ROOT / "experiments" / "market" / f"{name}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"missing scenario definition {path}")
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"scenario {path} did not parse to a mapping")
    return doc


def _scale_interventions(
    doc: dict[str, Any], symbol_map: dict[str, str], price_scale: dict[str, float]
) -> list[dict[str, Any]]:
    """Remap scenario interventions onto fixture tickers.

    The YAML scenarios are written for synthetic ACME/BETA at price 100.
    Symbol names are remapped to the fixture tickers and size-based
    quantities are scaled by the price ratio so the shock stays
    economically comparable. Structure and timing are unchanged.
    """
    out: list[dict[str, Any]] = []
    for iv in doc.get("interventions", []):
        iv = dict(iv)
        extra = dict(iv.get("extra") or {})
        raw_sym = extra.get("symbol")
        if raw_sym and raw_sym in symbol_map:
            new_sym = symbol_map[raw_sym]
            extra["symbol"] = new_sym
            if "quantity" in extra and new_sym in price_scale:
                extra["quantity"] = float(extra["quantity"]) * price_scale[new_sym]
        iv["extra"] = extra
        out.append(iv)
    return out


async def _run_scenario(
    scenario_name: str,
    hours: int,
    fixture_dir: Path,
) -> dict[str, Any]:
    from marketsim.engine import MarketSimEngine
    from marketsim.scenarios import market_scenario

    rows = _load_fixture_bars(fixture_dir)
    if not rows:
        raise EngineNotConfigured("market-sim: fixture produced no usable bars")

    t1_n = max(3, hours // 24)
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_ticker.setdefault(r["ticker"], []).append(r)
    tickers = sorted(by_ticker)
    for t in tickers:
        by_ticker[t].sort(key=lambda r: r["date"])
    min_bars = min(len(v) for v in by_ticker.values())
    if min_bars < t1_n + 5:
        raise EngineNotConfigured(
            f"market-sim: fixture has {min_bars} bars per ticker but needs at "
            f"least {t1_n + 5} ({t1_n} held-out t1 bars plus grounding history)"
        )

    doc = _load_scenario_doc(scenario_name)
    yaml_symbols = [str(s) for s in (doc.get("conditions", {}) or {}).get("symbols", [])]
    if not yaml_symbols:
        raise EngineNotConfigured(f"market-sim: scenario {scenario_name} defines no symbols")
    symbols = tickers[: len(yaml_symbols)]
    symbol_map = {old: new for old, new in zip(yaml_symbols, symbols)}

    t0_rows: dict[str, list[dict[str, Any]]] = {}
    t1_rows: dict[str, list[dict[str, Any]]] = {}
    for t in symbols:
        t0_rows[t] = by_ticker[t][:-t1_n]
        t1_rows[t] = by_ticker[t][-t1_n:]
    cutoff = _parse_ts(t0_rows[symbols[0]][-1]["date"])

    t0_events: list[WorldEvent] = []
    idx = 0
    for t in symbols:
        for r in t0_rows[t]:
            t0_events.append(_bar_event(idx, t, r["close"], _parse_ts(r["date"])))
            idx += 1
    t1_events: list[WorldEvent] = []
    for t in symbols:
        for r in t1_rows[t]:
            t1_events.append(_bar_event(idx, t, r["close"], _parse_ts(r["date"])))
            idx += 1

    snapshot = build_market_snapshot(t0_events)
    world = WorldState(
        world_id=f"market-sim-{scenario_name}",
        timestamp=cutoff.isoformat(),
        information_cutoff=cutoff.isoformat(),
        economy=Economy(indicators={"market_snapshot": snapshot}),
    )

    price_scale: dict[str, float] = {}
    initial_prices: dict[str, float] = {}
    for old, new in symbol_map.items():
        yaml_price = float((doc.get("conditions", {}) or {}).get("initial_prices", {}).get(old, 100.0))
        live_price = float(t0_rows[new][-1]["close"])
        initial_prices[new] = live_price
        price_scale[new] = live_price / yaml_price if yaml_price > 0 else 1.0

    conditions = doc.get("conditions", {}) or {}
    base_seed = int(doc.get("random_seed", 202411))
    seeds = [base_seed, base_seed + DEFAULT_SEEDS_OFFSET]
    population = int((doc.get("agents", {}) or {}).get("population", 60))
    interventions = _scale_interventions(doc, symbol_map, price_scale)

    predicted: dict[str, list[list[float]]] = {s: [] for s in symbols}
    for seed in seeds:
        sc = market_scenario(
            scenario_name,
            symbols,
            simulated_hours=hours,
            population=population,
            random_seed=seed,
            origin=cutoff.isoformat(),
            initial_prices=initial_prices,
            agent_mix=dict(conditions.get("agent_mix") or {}),
            interventions=interventions,
        )
        engine = MarketSimEngine(scenario=sc)
        sim = await engine.initialize(world, Population(synthetic_n=population))
        until = sim.origin + timedelta(hours=hours)
        result = await engine.run(sim, until)
        for s in symbols:
            predicted[s].append([float(v) for v in result.predicted_series.get(s, [])])

    # Mean over seeds, then downsample hourly mids to daily closes so the
    # simulated series lines up with the daily observed bars.
    daily_pred: dict[str, list[float]] = {}
    for s in symbols:
        runs = [r for r in predicted[s] if r]
        if not runs:
            continue
        n = min(len(r) for r in runs)
        mean_hourly = [sum(r[i] for r in runs) / len(runs) for i in range(n)]
        daily = [mean_hourly[i] for i in range(23, len(mean_hourly), 24)]
        if daily:
            daily_pred[s] = daily

    observed = observed_price_series(t1_events)
    ledger = RealityLedger()
    alignment, _rec_ids, _evals = record_market_alignment(
        ledger,
        experiment_id="market-sim-cli",
        scenario_id=scenario_name,
        engine_name="marketsim",
        seed=None,
        predicted=daily_pred,
        observed=observed,
        cutoff=cutoff,
        input_kinds=["observed"],
        n_seeds=len(seeds),
    )
    trust = scenario_trust_from_ledger(ledger.for_experiment("market-sim-cli"))
    trust_dump: dict[str, dict[str, Any]] = {}
    for k, v in trust.items():
        d = v.model_dump()
        d["describe"] = v.describe()
        trust_dump[k] = d

    alignment_dump = alignment.model_dump()
    for sym, sa in alignment.symbols.items():
        n = sa.n_points
        entry = alignment_dump["symbols"][sym]
        entry["sim_daily"] = [round(float(v), 4) for v in daily_pred.get(sym, [])[:n]]
        obs_rows = observed.get(sym, [])
        entry["obs_daily"] = [round(float(c), 4) for _, c in obs_rows[:n]]

    return {
        "scenario": scenario_name,
        "hours": hours,
        "seeds": seeds,
        "symbols": symbols,
        "cutoff": cutoff.isoformat(),
        "t1_bars_per_symbol": t1_n,
        "alignment": alignment_dump,
        "trust": trust_dump,
        "disclaimer": (
            "SIMULATED. Scenario calibration against one realized window, "
            "not a forecast of market prices."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def run_market_scenario(
    scenario: str,
    hours: int,
    fixture_dir: Path | None = None,
) -> dict[str, Any]:
    """Run a market scenario end-to-end and return the run summary dict.

    Shared by the `eve-miro market-sim` CLI and the POST /market/run API.
    Offline-only: grounds WorldState(t0) from fixture bars, runs the
    marketsim scenario, aligns simulated daily paths against the held-out
    fixture window (the observed t1), and returns the same summary dict
    the dashboard file holds. Raises ValueError on bad input,
    FileNotFoundError on missing fixtures, EngineNotConfigured when the
    fixture cannot ground a run.
    """
    if scenario not in SCENARIOS:
        raise ValueError(
            f"unknown scenario {scenario!r} (expected one of {', '.join(SCENARIOS)})"
        )
    if hours < MIN_HOURS:
        raise ValueError(
            f"hours must be at least {MIN_HOURS} (needs 3 daily bars to align)"
        )
    from eve_miro.paths import REPO_ROOT

    fdir = fixture_dir or (REPO_ROOT / "datasets" / "fixtures")
    return asyncio.run(_run_scenario(scenario, hours, fdir))


def cmd_market_sim(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eve-miro market-sim")
    parser.add_argument(
        "--scenario",
        choices=SCENARIOS,
        default=SCENARIOS[0],
        help="market scenario from experiments/market/",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=DEFAULT_HOURS,
        help="simulated horizon in hours (default 120)",
    )
    parser.add_argument(
        "--fixture-dir",
        default=None,
        help="override fixture directory (default: <repo>/datasets/fixtures)",
    )
    args = parser.parse_args(argv if argv is not None else [])

    if args.hours < MIN_HOURS:
        return fail(f"--hours must be at least {MIN_HOURS} (needs 3 daily bars to align)")
    fixture_dir = (
        Path(args.fixture_dir).expanduser()
        if args.fixture_dir
        else REPO_ROOT / "datasets" / "fixtures"
    )

    try:
        summary = run_market_scenario(args.scenario, args.hours, fixture_dir)
    except FileNotFoundError as exc:
        return fail(str(exc))
    except EngineNotConfigured as exc:
        return fail(str(exc))
    except ValueError as exc:
        return fail(str(exc))

    path = write_market_summary(summary)

    alignment = summary["alignment"]
    trust = summary["trust"]
    print(f"market-sim  scenario={summary['scenario']}  hours={summary['hours']}  "
          f"symbols={','.join(summary['symbols'])}")
    print(f"cutoff={summary['cutoff']}  t1_bars_per_symbol={summary['t1_bars_per_symbol']}")
    print(f"aggregate alignment score: {alignment['aggregate_score']:.4f}  "
          f"(class={alignment['scenario_class']})")
    for sym, sa in alignment["symbols"].items():
        print(
            f"  {sym}: score={sa['symbol_score']:.4f}  ks={sa['ks_statistic']:.4f}  "
            f"vol_mae={sa['vol_path_mae']:.4f}  dd_err={sa['drawdown_error']:.4f}"
        )
    if alignment["skipped_symbols"]:
        print(f"  skipped: {', '.join(alignment['skipped_symbols'])}")
    print("scenario-class trust:")
    for sclass in sorted(trust):
        t = trust[sclass]
        print(f"  [{t['recommendation']}] {sclass}  score={t['score']:.4f}")
        print(f"    {t['describe']}")
        print(f"    {t['notes']}")
    print(f"summary written to {path}")
    print(summary["disclaimer"])
    return 0
