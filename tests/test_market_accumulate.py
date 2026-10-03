"""Tests for eve-miro market-accumulate: weekly trust accumulation.

The fetch and simulate layers are mocked; these tests cover ledger
append/idempotency, trust recomputation from the full ledger file,
optional-context soft skips, and fail-closed behavior. No network.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from eve_miro.cli.main import COMMANDS
from eve_miro.cli.market_accumulate import (
    accumulate_week,
    build_ledger_record,
    fetch_macro,
    iso_week,
    load_calibrated_agent_config,
    read_ledger,
    recompute_trust_summary,
)
from eve_miro.cli.market_sim import SCENARIOS
from eve_miro.core.orchestration.market_alignment import scenario_class_for
from eve_miro.errors import EngineNotConfigured, ProviderError


FAKE_KWARGS = {
    "market_maker": {"spread_bps": 60.0, "skew_k": 6.0, "size": 180.0},
    "momentum": {"lookback": 17, "threshold": 0.018},
    "noise": {"trade_prob": 0.8, "size": 115.0},
    "fundamental": {"tolerance": 0.03},
}
FAKE_MIX = {
    "market_maker": 0.05,
    "momentum": 0.05,
    "noise": 0.8,
    "fundamental": 0.1,
}


def _fake_summary(scenario: str, *, dd_err: float = 0.01, ks: float = 0.2,
                  score: float = 0.6) -> dict:
    sym = {
        "symbol_score": score,
        "ks_statistic": ks,
        "vol_path_mae": 0.05,
        "drawdown_error": dd_err,
        "n_points": 20,
    }
    return {
        "scenario": scenario,
        "hours": 480,
        "t1_bars_per_symbol": 20,
        "alignment": {
            "scenario_class": scenario_class_for(scenario),
            "aggregate_score": score,
            "symbols": {"SPY": dict(sym), "AAPL": dict(sym)},
            "skipped_symbols": [],
        },
    }


async def _fake_bars():
    return [
        {"ticker": t, "close": 100.0 + i, "date": f"2026-09-{i + 1:02d}"}
        for t in ("SPY", "AAPL")
        for i in range(30)
    ]


async def _none():
    return None


def _make_runner(calls: list):
    async def run(scenario, hours, fixture_dir, **kwargs):
        calls.append((scenario, hours, kwargs.get("experiment_id")))
        assert kwargs.get("agent_kwargs") == FAKE_KWARGS
        assert kwargs.get("agent_mix") == FAKE_MIX
        return _fake_summary(scenario)

    return run


def _paths(tmp_path: Path):
    ledger = tmp_path / "trust_ledger.jsonl"
    trust = tmp_path / "trust_summary.json"
    latest = tmp_path / "latest_market_run.json"
    return ledger, trust, latest


def test_command_wired():
    assert COMMANDS["market-accumulate"].__name__ == "cmd_market_accumulate"


def test_iso_week_format():
    from datetime import datetime, timezone

    assert iso_week(datetime(2026, 10, 5, tzinfo=timezone.utc)) == "2026-W41"


def test_accumulate_appends_then_skips_idempotently(tmp_path):
    ledger, trust, latest = _paths(tmp_path)
    calls: list = []
    kwargs = dict(
        week="2026-W41",
        fetch_bars=_fake_bars,
        fetch_vix_fn=_none,
        fetch_macro_fn=_none,
        fetch_news_fn=_none,
        run_scenario=_make_runner(calls),
        ledger_path=ledger,
        trust_summary_path=trust,
        latest_run_path=latest,
        agent_kwargs=FAKE_KWARGS,
        agent_mix=FAKE_MIX,
    )
    first = asyncio.run(accumulate_week(**kwargs))
    assert first["status"] == "ran"
    assert first["scenarios"] == list(SCENARIOS)
    assert len(calls) == len(SCENARIOS)
    assert calls[0][1] == 480
    assert calls[0][2] == "market-accumulate"

    second = asyncio.run(accumulate_week(**kwargs))
    assert second["status"] == "skipped"
    assert len(calls) == len(SCENARIOS)  # no duplicate simulations

    lines = ledger.read_text().strip().splitlines()
    assert len(lines) == len(SCENARIOS)
    recs = [json.loads(line) for line in lines]
    assert {r["scenario_class"] for r in recs} == {
        scenario_class_for(s) for s in SCENARIOS
    }
    assert all(r["week"] == "2026-W41" and r["data_source"] == "live" for r in recs)
    assert all(r["n_bars"] == 20 for r in recs)

    summary = json.loads(trust.read_text())
    assert summary["week"] == "2026-W41"
    assert summary["n_records"] == len(SCENARIOS)
    assert summary["classes"]["sell_shock"]["n_alignments"] == 1
    assert latest.is_file()


def test_partial_week_runs_only_missing(tmp_path):
    ledger, trust, latest = _paths(tmp_path)
    seed = build_ledger_record(
        week="2026-W41",
        run_at="2026-10-05T00:00:00+00:00",
        scenario="sell_shock_001",
        summary=_fake_summary("sell_shock_001"),
        tickers=("SPY", "AAPL"),
        vix=18.0,
        macro=None,
        news=None,
    )
    ledger.write_text(json.dumps(seed) + "\n")
    calls: list = []
    result = asyncio.run(
        accumulate_week(
            week="2026-W41",
            fetch_bars=_fake_bars,
            fetch_vix_fn=_none,
            fetch_macro_fn=_none,
            fetch_news_fn=_none,
            run_scenario=_make_runner(calls),
            ledger_path=ledger,
            trust_summary_path=trust,
            latest_run_path=latest,
            agent_kwargs=FAKE_KWARGS,
            agent_mix=FAKE_MIX,
        )
    )
    assert result["status"] == "ran"
    assert [c[0] for c in calls] == [s for s in SCENARIOS if s != "sell_shock_001"]
    assert len(ledger.read_text().strip().splitlines()) == len(SCENARIOS)


def test_trust_scores_move_as_ledger_grows(tmp_path):
    ledger, trust, latest = _paths(tmp_path)

    def rec(week, dd_err, ks):
        return build_ledger_record(
            week=week,
            run_at="2026-10-05T00:00:00+00:00",
            scenario="sell_shock_001",
            summary=_fake_summary("sell_shock_001", dd_err=dd_err, ks=ks),
            tickers=("SPY", "AAPL"),
            vix=None,
            macro=None,
            news=None,
        )

    one = recompute_trust_summary([rec("2026-W40", 0.01, 0.1)], "2026-W40")
    t1 = one["classes"]["sell_shock"]
    assert t1["n_alignments"] == 1
    assert t1["score"] == pytest.approx(0.96)
    assert t1["recommendation"] == "USE"

    two = recompute_trust_summary(
        [rec("2026-W40", 0.01, 0.1), rec("2026-W41", 0.5, 0.9)], "2026-W41"
    )
    t2 = two["classes"]["sell_shock"]
    assert t2["n_alignments"] == 2
    assert t2["score"] == pytest.approx(0.5)
    assert t2["score"] < t1["score"]
    assert t2["recommendation"] == "CAUTION"

    many = recompute_trust_summary(
        [rec("2026-W40", 0.01, 0.1)]
        + [rec(f"2026-W4{i}", 0.5, 0.9) for i in range(1, 5)],
        "2026-W44",
    )
    t3 = many["classes"]["sell_shock"]
    assert t3["n_alignments"] == 5
    assert t3["score"] < 0.40
    assert t3["recommendation"] == "DO_NOT_USE"

    # Untouched classes stay at zero with DO_NOT_USE.
    assert many["classes"]["rate_shock"]["n_alignments"] == 0
    assert many["classes"]["rate_shock"]["recommendation"] == "DO_NOT_USE"


def test_fred_absent_soft_skips(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert asyncio.run(fetch_macro()) is None


def test_live_fetch_failure_raises_and_writes_nothing(tmp_path):
    ledger, trust, latest = _paths(tmp_path)

    async def boom():
        raise ProviderError("yfinance down")

    with pytest.raises(ProviderError):
        asyncio.run(
            accumulate_week(
                week="2026-W41",
                fetch_bars=boom,
                fetch_vix_fn=_none,
                fetch_macro_fn=_none,
                fetch_news_fn=_none,
                run_scenario=_make_runner([]),
                ledger_path=ledger,
                trust_summary_path=trust,
                latest_run_path=latest,
                agent_kwargs=FAKE_KWARGS,
                agent_mix=FAKE_MIX,
            )
        )
    assert not ledger.exists()
    assert not trust.exists()


def test_corrupt_ledger_line_fails_closed(tmp_path):
    ledger = tmp_path / "trust_ledger.jsonl"
    ledger.write_text('{"week": "2026-W40"}\nnot json\n')
    with pytest.raises(ValueError, match="corrupt ledger line 2"):
        read_ledger(ledger)


def test_missing_calibration_result_fails_closed(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_calibrated_agent_config(tmp_path / "nope.json")


def test_load_calibrated_agent_config_reads_committed_result():
    from eve_miro.paths import REPO_ROOT

    kwargs, mix = load_calibrated_agent_config(
        REPO_ROOT / "storage" / "market" / "calibration_result.json"
    )
    assert set(kwargs) == {"market_maker", "momentum", "noise", "fundamental"}
    assert kwargs["market_maker"]["spread_bps"] > 0
    assert kwargs["momentum"]["lookback"] == int(kwargs["momentum"]["lookback"])
    assert abs(sum(mix.values()) - 1.0) < 1e-9


def test_build_agents_applies_calibrated_kwargs():
    from marketsim.engine import MarketSimEngine

    eng = MarketSimEngine()
    agents = eng._build_agents(
        ["SPY"],
        10,
        123,
        {"noise": 1.0},
        {"noise": {"trade_prob": 0.9, "size": 42.0}},
    )
    noise_agents = [a for a in agents if type(a).__name__ == "NoiseTrader"]
    assert noise_agents
    assert all(a.trade_prob == 0.9 and a.size == 42.0 for a in noise_agents)


def test_build_agents_rejects_bad_kwarg():
    from marketsim.engine import MarketSimEngine

    eng = MarketSimEngine()
    with pytest.raises(EngineNotConfigured, match="agent_kwargs"):
        eng._build_agents(
            ["SPY"], 10, 123, {"noise": 1.0}, {"noise": {"nope": 1.0}}
        )


def test_build_agents_fundamental_gets_fair_value():
    from marketsim.engine import MarketSimEngine

    eng = MarketSimEngine()
    agents = eng._build_agents(
        ["SPY"],
        10,
        123,
        {"fundamental": 1.0},
        {"fundamental": {"tolerance": 0.03}},
        {"SPY": 250.0},
    )
    funds = [a for a in agents if type(a).__name__ == "FundamentalTrader"]
    assert funds
    assert all(a.fair_value == 250.0 and a.tolerance == 0.03 for a in funds)
