"""eve-miro market-accumulate: weekly trust accumulation from live data.

Runs every scenario against the latest live market state, aligns each
simulated path with the most recent realized window, and appends one
record per scenario per ISO week to the trust ledger
(``storage/market/trust_ledger.jsonl``). The per-class trust summary is
recomputed from the full ledger file on every run and written to
``storage/market/trust_summary.json``; ``latest_market_run.json`` is
refreshed so the dashboard Market tab shows the newest run.

Data: live yfinance daily bars for SPY and AAPL (fail closed when
unavailable), live VIX for context (soft-fail), FRED macro when
FRED_API_KEY is set (soft skip otherwise), GDELT market news counts
(soft skip on failure). Nothing is fabricated: a failed fetch is an
error for bars and a recorded skip for the optional context.

Idempotency: records are keyed by ISO week (e.g. "2026-W40"). A week
with all three scenario records already present exits 0 without
duplicating; a partially recorded week only runs the missing scenarios.

Trust here measures scenario-class calibration on observed windows,
never predictive power. See docs/market-accumulation.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from eve_miro.cli.market_sim import (
    SCENARIOS,
    _run_scenario,
    summary_path,
)
from eve_miro.core.calibration.params import CalibrationParams
from eve_miro.core.orchestration.market_alignment import scenario_class_for
from eve_miro.core.reality.jev_scoring import (
    JEV_NOTE,
    build_market_state,
    jev_enabled,
    judge_alignment,
    render_market_state,
    score_scenario_relevance,
)
from eve_miro.core.reality.trust_profile import scenario_trust_from_ledger
from eve_miro.errors import EngineNotConfigured, ProviderError
from eve_miro.paths import REPO_ROOT

TICKERS = ("SPY", "AAPL", "QQQ", "IWM")
ACCUM_HOURS = 480  # 20 trading days of simulated horizon
MIN_BARS_PER_TICKER = 25  # 20-day realized window plus grounding history
EXPERIMENT_ID = "market-accumulate"
FRED_KEY_ENV = "FRED_API_KEY"

LEDGER_PATH = REPO_ROOT / "storage" / "market" / "trust_ledger.jsonl"
TRUST_SUMMARY_PATH = REPO_ROOT / "storage" / "market" / "trust_summary.json"
CALIBRATION_RESULT_PATH = (
    REPO_ROOT / "storage" / "market" / "calibration_result.json"
)

TRUST_DISCLAIMER = (
    "Trust measures scenario-class calibration against observed market "
    "windows, not predictive power. Scores move only as the ledger "
    "accumulates independent weekly alignments."
)


def fail(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 1


def iso_week(dt: datetime) -> str:
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


# -- live data fetching -------------------------------------------------


async def fetch_live_bars(
    tickers: tuple[str, ...] = TICKERS,
) -> list[dict[str, Any]]:
    """Fetch live daily bars via yfinance. Fail closed on any problem.

    Returns fixture-shaped rows (ticker/close/date). Drops a trailing bar
    dated today (UTC) because it is an incomplete session, so the
    realized window always ends on the latest complete bar.
    """
    from eve_miro.providers.markets_bars import download_history

    async def one(ticker: str) -> list[dict[str, Any]]:
        payload = await asyncio.to_thread(
            download_history, ticker, period="1y", interval="1d"
        )
        return payload.get("bars") or []

    rows: list[dict[str, Any]] = []
    today = datetime.now(timezone.utc).date()
    for ticker in tickers:
        try:
            bars = await one(ticker)
        except Exception as exc:
            raise ProviderError(
                f"live bars fetch failed for {ticker}: {exc}"
            ) from exc
        kept = 0
        for bar in bars:
            close = bar.get("close")
            date = bar.get("date")
            if not isinstance(close, (int, float)) or not date:
                continue
            try:
                bar_date = datetime.fromisoformat(
                    str(date).replace("Z", "+00:00")
                ).date()
            except ValueError:
                continue
            if bar_date >= today:
                continue  # incomplete session
            rows.append(
                {"ticker": ticker, "close": float(close), "date": str(date)}
            )
            kept += 1
        if kept < MIN_BARS_PER_TICKER:
            raise ProviderError(
                f"live bars for {ticker}: only {kept} complete bars, "
                f"need at least {MIN_BARS_PER_TICKER}"
            )
    if not rows:
        raise ProviderError("live bars fetch produced no usable rows")
    return rows


async def fetch_vix() -> float | None:
    """Latest live VIX close for ledger context. Soft-fail: None on error."""
    from eve_miro.providers.markets_bars import download_history

    try:
        payload = await asyncio.to_thread(
            download_history, "^VIX", period="1mo", interval="1d"
        )
        bars = [b for b in (payload.get("bars") or []) if b.get("close")]
        if not bars:
            return None
        return float(bars[-1]["close"])
    except Exception as exc:
        print(f"warn: VIX fetch failed ({exc}); continuing without it")
        return None


async def fetch_macro() -> dict[str, Any] | None:
    """FRED macro snapshot when FRED_API_KEY is set. Soft skip otherwise."""
    if not (os.environ.get(FRED_KEY_ENV) or "").strip():
        print("note: FRED_API_KEY not set; skipping macro snapshot")
        return None
    try:
        from eve_miro.providers.macro_fred import _live_payload

        payload = await _live_payload()
        out: dict[str, Any] = {}
        for series_id, series in (payload.get("series") or {}).items():
            obs = (series.get("observations") or [])
            if obs:
                out[series_id] = {
                    "date": obs[0].get("date"),
                    "value": obs[0].get("value"),
                }
        return out or None
    except Exception as exc:
        print(f"warn: FRED fetch failed ({exc}); continuing without macro")
        return None


async def fetch_news_counts() -> dict[str, Any] | None:
    """GDELT market-news article count for context. Soft skip on failure."""
    try:
        from eve_miro.providers.common import http_get_json
        from eve_miro.providers.news_markets import DOC_URL, QUERY

        payload = await http_get_json(
            DOC_URL,
            params={
                "query": QUERY,
                "mode": "ArtList",
                "maxrecords": 10,
                "format": "json",
            },
            timeout=20.0,
        )
        articles = (payload or {}).get("articles") or []
        return {"n_articles": len(articles), "query": QUERY}
    except Exception as exc:
        print(f"warn: GDELT fetch failed ({exc}); continuing without news")
        return None


# -- calibrated parameters ----------------------------------------------


def load_calibrated_agent_config(
    path: Path = CALIBRATION_RESULT_PATH,
) -> tuple[dict[str, dict[str, Any]], dict[str, float]]:
    """Load Phase 5 best-fit params; return (agent_kwargs, agent_mix).

    Raises FileNotFoundError/ValueError when the committed calibration
    result is missing or malformed: running uncalibrated while claiming
    calibration would be fabrication.
    """
    if not path.is_file():
        raise FileNotFoundError(
            f"calibration result missing at {path}; cannot run the "
            "accumulation job without the Phase 5 fitted parameters"
        )
    doc = json.loads(path.read_text(encoding="utf-8"))
    params = CalibrationParams.from_dict(doc["best"]["params"])
    kwargs = {
        "market_maker": params.market_maker_kwargs(),
        "momentum": params.momentum_kwargs(),
        "noise": params.noise_kwargs(),
        "fundamental": {"tolerance": params["fund_tolerance"]},
    }
    counts = params.agent_counts(60)
    total = sum(counts.values()) or 1
    mix = {
        "market_maker": counts["market_maker"] / total,
        "momentum": counts["momentum"] / total,
        "noise": counts["noise"] / total,
        "fundamental": counts["fundamental"] / total,
    }
    return kwargs, mix


# -- ledger ----------------------------------------------------------------


def read_ledger(path: Path = LEDGER_PATH) -> list[dict[str, Any]]:
    """Read the JSONL trust ledger. Fail closed on corrupt lines."""
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for lineno, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"corrupt ledger line {lineno} in {path}: {exc}"
            ) from exc
        if not isinstance(rec, dict) or "week" not in rec:
            raise ValueError(
                f"corrupt ledger line {lineno} in {path}: not a record"
            )
        records.append(rec)
    return records


def append_ledger(records: list[dict[str, Any]], path: Path = LEDGER_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def records_for_week(
    records: list[dict[str, Any]], week: str
) -> dict[str, dict[str, Any]]:
    """Map scenario_class to its record for the given ISO week."""
    return {
        str(r.get("scenario_class")): r
        for r in records
        if r.get("week") == week
    }


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def ledger_record_for_trust(rec: dict[str, Any]) -> dict[str, Any]:
    """Project a JSONL record onto the shape scenario_trust_from_ledger reads."""
    alignment = rec.get("alignment") or {}
    symbols = alignment.get("symbols") or {}
    dd_errors = [
        s.get("drawdown_error")
        for s in symbols.values()
        if isinstance(s.get("drawdown_error"), (int, float))
    ]
    ks_stats = [
        s.get("ks_statistic")
        for s in symbols.values()
        if isinstance(s.get("ks_statistic"), (int, float))
    ]
    return {
        "domain": "market",
        "scenario_class": rec.get("scenario_class", "baseline"),
        "metrics": {
            "drawdown_error": _mean([float(v) for v in dd_errors]) or 0.0,
            "ks_statistic": _mean([float(v) for v in ks_stats]) or 1.0,
        },
    }


def recompute_trust_summary(
    records: list[dict[str, Any]], week: str
) -> dict[str, Any]:
    """Recompute per-class trust from the full ledger (never from memory)."""
    trust = scenario_trust_from_ledger(
        [ledger_record_for_trust(r) for r in records]
    )
    classes: dict[str, Any] = {}
    for sclass, t in trust.items():
        d = t.model_dump()
        d["describe"] = t.describe()
        classes[sclass] = d
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "week": week,
        "n_records": len(records),
        "classes": classes,
        "disclaimer": TRUST_DISCLAIMER,
    }


def write_trust_summary(summary: dict[str, Any], path: Path = TRUST_SUMMARY_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return path


# -- accumulation ------------------------------------------------------------


FetchBars = Callable[[], Awaitable[list[dict[str, Any]]]]
RunScenario = Callable[..., Awaitable[dict[str, Any]]]


def build_ledger_record(
    *,
    week: str,
    run_at: str,
    scenario: str,
    summary: dict[str, Any],
    tickers: tuple[str, ...],
    vix: float | None,
    macro: dict[str, Any] | None,
    news: dict[str, Any] | None,
    jev_relevance: float | None = None,
    jev_judge_score: float | None = None,
) -> dict[str, Any]:
    """Build one JSONL ledger record.

    Jev fields are weak-signal annotations only: they are recorded for
    attention and never ingested by the trust computation (see
    ledger_record_for_trust, which projects an explicit field set).
    """
    alignment = summary.get("alignment") or {}
    symbols = alignment.get("symbols") or {}
    sym_out: dict[str, Any] = {}
    for sym, sa in symbols.items():
        sym_out[sym] = {
            "symbol_score": sa.get("symbol_score"),
            "ks_statistic": sa.get("ks_statistic"),
            "vol_path_mae": sa.get("vol_path_mae"),
            "drawdown_error": sa.get("drawdown_error"),
            "n_points": sa.get("n_points"),
        }
    return {
        "week": week,
        "run_at": run_at,
        "scenario": scenario,
        "scenario_class": alignment.get("scenario_class")
        or scenario_class_for(scenario),
        "tickers": list(tickers),
        "hours": summary.get("hours"),
        "n_bars": summary.get("t1_bars_per_symbol"),
        "vix": vix,
        "macro": macro,
        "news": news,
        "jev_relevance": jev_relevance,
        "alignment": {
            "aggregate_score": alignment.get("aggregate_score"),
            "symbols": sym_out,
            "skipped_symbols": alignment.get("skipped_symbols", []),
            "jev_judge_score": jev_judge_score,
        },
        "data_source": "live",
    }


def render_sim_summary(scenario: str, summary: dict[str, Any]) -> str:
    """Render a simulated scenario outcome as text for the Jev judge."""
    alignment = summary.get("alignment") or {}
    lines = [
        f"Scenario {scenario} "
        f"(class {alignment.get('scenario_class')}), "
        f"{summary.get('hours')}h horizon."
    ]
    agg = alignment.get("aggregate_score")
    lines.append(
        f"Aggregate alignment score: {agg:.3f}"
        if isinstance(agg, (int, float))
        else "Aggregate alignment score: n/a"
    )
    for sym, sa in (alignment.get("symbols") or {}).items():
        lines.append(
            f"{sym}: symbol score {sa.get('symbol_score')}, "
            f"KS {sa.get('ks_statistic')}, "
            f"vol-path MAE {sa.get('vol_path_mae')}, "
            f"drawdown error {sa.get('drawdown_error')}"
        )
    skipped = alignment.get("skipped_symbols") or []
    if skipped:
        lines.append(f"Skipped symbols: {', '.join(skipped)}")
    return "\n".join(lines)


async def accumulate_week(
    *,
    week: str,
    fetch_bars: FetchBars,
    fetch_vix_fn: Callable[[], Awaitable[float | None]] = fetch_vix,
    fetch_macro_fn: Callable[[], Awaitable[dict[str, Any] | None]] = fetch_macro,
    fetch_news_fn: Callable[[], Awaitable[dict[str, Any] | None]] = fetch_news_counts,
    run_scenario: RunScenario | None = None,
    ledger_path: Path = LEDGER_PATH,
    trust_summary_path: Path = TRUST_SUMMARY_PATH,
    latest_run_path: Path | None = None,
    agent_kwargs: dict[str, dict[str, Any]] | None = None,
    agent_mix: dict[str, float] | None = None,
    jev: bool | None = None,
    score_relevance_fn: Callable[[dict[str, Any]], dict[str, float | None] | None] | None = None,
    judge_fn: Callable[[str, str], float | None] | None = None,
) -> dict[str, Any]:
    """Run one accumulation week. Returns a result dict; raises fail-closed.

    fetch_bars raising is fatal (no bars, no ledger entries). The optional
    context fetchers soft-fail to None by contract.
    """
    run = run_scenario or _run_scenario
    existing = records_for_week(read_ledger(ledger_path), week)
    pending = [
        s for s in SCENARIOS if scenario_class_for(s) not in existing
    ]
    if not pending:
        return {"week": week, "status": "skipped", "reason": "week already recorded"}

    if agent_kwargs is None or agent_mix is None:
        agent_kwargs, agent_mix = load_calibrated_agent_config()

    bars = await fetch_bars()
    vix = await fetch_vix_fn()
    macro = await fetch_macro_fn()
    news = await fetch_news_fn()

    use_jev = jev_enabled() if jev is None else jev
    relevance_fn = score_relevance_fn or score_scenario_relevance
    judge = judge_fn or judge_alignment
    market_state = build_market_state(bars, vix)
    realized_text = render_market_state(market_state)
    relevance: dict[str, float | None] | None = None
    if use_jev:
        print("note: Jev scoring enabled (JEV_ENABLED=1); weak signal only")
        try:
            relevance = relevance_fn(market_state)
        except Exception as exc:
            print(f"note: Jev relevance scoring skipped ({exc})")
            relevance = None
    else:
        print("note: Jev scoring disabled; set JEV_ENABLED=1 to enable")

    run_at = datetime.now(timezone.utc).isoformat()
    new_records: list[dict[str, Any]] = []
    summaries: dict[str, dict[str, Any]] = {}
    for scenario in pending:
        summary = await run(
            scenario,
            ACCUM_HOURS,
            REPO_ROOT / "datasets" / "fixtures",
            bars=bars,
            agent_kwargs=agent_kwargs,
            agent_mix=agent_mix,
            experiment_id=EXPERIMENT_ID,
        )
        summaries[scenario] = summary
        sclass = summary.get("alignment", {}).get("scenario_class") or scenario_class_for(
            scenario
        )
        judge_score: float | None = None
        if use_jev:
            try:
                judge_score = judge(
                    render_sim_summary(scenario, summary), realized_text
                )
            except Exception as exc:
                print(f"note: Jev judge skipped for {scenario} ({exc})")
        new_records.append(
            build_ledger_record(
                week=week,
                run_at=run_at,
                scenario=scenario,
                summary=summary,
                tickers=TICKERS,
                vix=vix,
                macro=macro,
                news=news,
                jev_relevance=(relevance or {}).get(sclass),
                jev_judge_score=judge_score,
            )
        )

    append_ledger(new_records, ledger_path)
    all_records = read_ledger(ledger_path)
    trust_summary = recompute_trust_summary(all_records, week)
    write_trust_summary(trust_summary, trust_summary_path)

    # Refresh the dashboard's latest run: newest scenario summary with the
    # ledger-wide trust table instead of the single-run one.
    trust_dump: dict[str, Any] = {}
    for sclass, t in trust_summary["classes"].items():
        trust_dump[sclass] = t
    latest = summaries[pending[-1]]
    latest["trust"] = trust_dump
    latest["accumulation_week"] = week
    # Jev relevance is a weak attention signal, kept structurally separate
    # from the empirical trust table above.
    latest["jev_relevance"] = relevance or {}
    if use_jev:
        latest["jev_note"] = JEV_NOTE
    latest["disclaimer"] = (
        "SIMULATED. Scenario calibration against one realized window, "
        "not a forecast of market prices. Trust scores are per scenario "
        "class from the accumulation ledger."
    )
    out_path = latest_run_path or summary_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(latest, indent=2), encoding="utf-8")

    return {
        "week": week,
        "status": "ran",
        "scenarios": pending,
        "n_records": len(all_records),
        "jev_relevance": relevance or {},
        "trust": {
            sclass: {
                "score": t["score"],
                "n_alignments": t["n_alignments"],
                "recommendation": t["recommendation"],
            }
            for sclass, t in trust_summary["classes"].items()
        },
    }


def cmd_market_accumulate(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eve-miro market-accumulate")
    parser.add_argument(
        "--week",
        default=None,
        help="ISO week override like 2026-W40 (default: current week). "
        "To re-run a week manually, pass an unrecorded label such as 2026-W40b.",
    )
    args = parser.parse_args(argv if argv is not None else [])

    week = args.week or iso_week(datetime.now(timezone.utc))

    async def _main() -> dict[str, Any]:
        return await accumulate_week(
            week=week, fetch_bars=lambda: fetch_live_bars(TICKERS)
        )

    try:
        result = asyncio.run(_main())
    except (ProviderError, EngineNotConfigured, FileNotFoundError, ValueError) as exc:
        return fail(str(exc))

    if result["status"] == "skipped":
        print(f"market-accumulate  week={week}: {result['reason']}; nothing to do")
        return 0

    print(f"market-accumulate  week={week}  scenarios={','.join(result['scenarios'])}")
    print(f"ledger records total: {result['n_records']}")
    if result.get("jev_relevance"):
        print("Jev relevance (weak signal, not trust):")
        for sclass in sorted(result["jev_relevance"]):
            score = result["jev_relevance"][sclass]
            print(f"  {sclass}: {score:.2f}" if isinstance(score, float) else f"  {sclass}: n/a")
        print(JEV_NOTE)
    print("per-class trust (ledger-wide):")
    for sclass in sorted(result["trust"]):
        t = result["trust"][sclass]
        print(
            f"  [{t['recommendation']}] {sclass}  "
            f"score={t['score']:.4f}  n={t['n_alignments']}"
        )
    print(f"ledger: {LEDGER_PATH}")
    print(f"trust summary: {TRUST_SUMMARY_PATH}")
    print(TRUST_DISCLAIMER)
    return 0
