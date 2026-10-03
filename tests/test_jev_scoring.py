"""Tests for Jev (TypeSafe) weak-signal scoring in the accumulation run.

The Jev HTTP layer is mocked; these tests cover relevance scoring shape,
judge score normalization and storage, fail-soft behavior, the
JEV_ENABLED opt-in gate, and the rule that trust computation never
ingests Jev fields. No network.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import eve_miro.core.reality.jev_scoring as jev
from eve_miro.cli.market_accumulate import (
    TICKERS,
    accumulate_week,
    build_ledger_record,
    recompute_trust_summary,
)
from eve_miro.cli.market_sim import SCENARIOS
from eve_miro.core.orchestration.market_alignment import scenario_class_for


def _answers_for(classes, score=1.7):
    answers = {}
    for sclass in classes:
        answers[f"relevance_{sclass}"] = {
            "type": "score",
            "score": score,
            "confidence": 0.5,
            "legend": {"0": "a", "1": "b", "2": "c", "3": "d"},
        }
    return {"model": "jev-test", "answers": answers}


def _enable(monkeypatch):
    monkeypatch.setenv("JEV_ENABLED", "1")


def test_relevance_shape_and_normalization(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(
        jev, "_post_decide", lambda state, questions, timeout=30: _answers_for(jev.RELEVANCE_CLASSES)
    )
    out = jev.score_scenario_relevance({"vix": 18.0, "window_days": 20, "tickers": {}})
    assert out is not None
    assert set(out) == set(jev.RELEVANCE_CLASSES)
    # 1.7 on a 0..3 scale normalizes to 0.5667
    assert out["sell_shock"] == pytest.approx(1.7 / 3)
    assert all(isinstance(v, float) and 0.0 <= v <= 1.0 for v in out.values())


def test_relevance_disabled_without_env(monkeypatch):
    monkeypatch.delenv("JEV_ENABLED", raising=False)
    called = []
    monkeypatch.setattr(
        jev, "_post_decide", lambda *a, **k: called.append(True) or {}
    )
    assert jev.score_scenario_relevance({}) is None
    assert jev.judge_alignment("sim", "realized") is None
    assert called == []


def test_relevance_fail_soft_on_api_error(monkeypatch):
    _enable(monkeypatch)

    def boom(state, questions, timeout=30):
        raise RuntimeError("network down")

    monkeypatch.setattr(jev, "_post_decide", boom)
    assert jev.score_scenario_relevance({"vix": 20.0}) is None
    assert jev.judge_alignment("sim", "realized") is None


def test_relevance_fail_soft_on_none_response(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(jev, "_post_decide", lambda *a, **k: None)
    assert jev.score_scenario_relevance({"vix": 20.0}) is None


def test_judge_normalization(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(
        jev,
        "_post_decide",
        lambda state, questions, timeout=30: {
            "answers": {
                "judge": {
                    "type": "score",
                    "score": 2.4,
                    "legend": {"0": "a", "1": "b", "2": "c", "3": "d"},
                }
            }
        },
    )
    assert jev.judge_alignment("sim text", "realized text") == pytest.approx(2.4 / 3)


def test_judge_unparseable_answer_is_none(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(
        jev, "_post_decide", lambda *a, **k: {"answers": {"judge": {"score": "high"}}}
    )
    assert jev.judge_alignment("sim", "realized") is None


def test_build_market_state_arithmetic():
    bars = [
        {"ticker": "SPY", "close": 100.0 + i, "date": f"2026-09-{i + 1:02d}"}
        for i in range(25)
    ]
    state = jev.build_market_state(bars, 18.5, window=20)
    assert state["vix"] == 18.5
    spy = state["tickers"]["SPY"]
    assert spy["trailing_vol"] is not None and spy["trailing_vol"] > 0
    assert spy["max_drawdown"] == pytest.approx(0.0)  # monotonic rise
    # window=20 keeps the last 20 closes: 105.0 .. 124.0
    assert spy["trend"] == pytest.approx(124.0 / 105.0 - 1.0, rel=1e-3)
    text = jev.render_market_state(state)
    assert "VIX: 18.5" in text and "SPY" in text


def test_trust_ignores_jev_fields():
    def rec(with_jev: bool):
        summary = {
            "scenario": "sell_shock_001",
            "hours": 480,
            "t1_bars_per_symbol": 20,
            "alignment": {
                "scenario_class": "sell_shock",
                "aggregate_score": 0.6,
                "symbols": {
                    "SPY": {
                        "symbol_score": 0.6,
                        "ks_statistic": 0.2,
                        "vol_path_mae": 0.05,
                        "drawdown_error": 0.01,
                        "n_points": 20,
                    }
                },
                "skipped_symbols": [],
            },
        }
        return build_ledger_record(
            week="2026-W41",
            run_at="2026-10-05T00:00:00+00:00",
            scenario="sell_shock_001",
            summary=summary,
            tickers=TICKERS,
            vix=18.0,
            macro=None,
            news=None,
            jev_relevance=0.95 if with_jev else None,
            jev_judge_score=0.05 if with_jev else None,
        )

    plain = recompute_trust_summary([rec(False)], "2026-W41")
    annotated = recompute_trust_summary([rec(True)], "2026-W41")
    assert annotated["classes"]["sell_shock"]["score"] == pytest.approx(
        plain["classes"]["sell_shock"]["score"]
    )
    assert annotated["classes"]["sell_shock"]["n_alignments"] == 1
    # the weak-signal fields are still recorded on the record itself
    assert rec(True)["jev_relevance"] == 0.95
    assert rec(True)["alignment"]["jev_judge_score"] == 0.05


def test_ticker_universe_expanded():
    assert TICKERS == ("SPY", "AAPL", "QQQ", "IWM")


def _fake_summary(scenario: str) -> dict:
    sym = {
        "symbol_score": 0.6,
        "ks_statistic": 0.2,
        "vol_path_mae": 0.05,
        "drawdown_error": 0.01,
        "n_points": 20,
    }
    return {
        "scenario": scenario,
        "hours": 480,
        "t1_bars_per_symbol": 20,
        "alignment": {
            "scenario_class": scenario_class_for(scenario),
            "aggregate_score": 0.6,
            "symbols": {"SPY": dict(sym)},
            "skipped_symbols": [],
        },
    }


async def _fake_bars():
    return [
        {"ticker": t, "close": 100.0 + i, "date": f"2026-09-{i + 1:02d}"}
        for t in TICKERS
        for i in range(30)
    ]


async def _none():
    return None


def _accum_kwargs(tmp_path: Path, **extra):
    return dict(
        week="2026-W42",
        fetch_bars=_fake_bars,
        fetch_vix_fn=_none,
        fetch_macro_fn=_none,
        fetch_news_fn=_none,
        run_scenario=_runner,
        ledger_path=tmp_path / "trust_ledger.jsonl",
        trust_summary_path=tmp_path / "trust_summary.json",
        latest_run_path=tmp_path / "latest_market_run.json",
        agent_kwargs={"market_maker": {}, "momentum": {}, "noise": {}, "fundamental": {}},
        agent_mix={"market_maker": 0.1, "momentum": 0.1, "noise": 0.7, "fundamental": 0.1},
        **extra,
    )


async def _runner(scenario, hours, fixture_dir, **kwargs):
    return _fake_summary(scenario)


def test_accumulate_wires_jev_fields(tmp_path):
    relevance_calls = []
    judge_calls = []

    def fake_relevance(state):
        relevance_calls.append(state)
        return {s: 0.75 for s in jev.RELEVANCE_CLASSES}

    def fake_judge(sim_text, realized_text):
        judge_calls.append((sim_text, realized_text))
        assert "Scenario" in sim_text
        return 0.6

    result = asyncio.run(
        accumulate_week(
            **_accum_kwargs(
                tmp_path,
                jev=True,
                score_relevance_fn=fake_relevance,
                judge_fn=fake_judge,
            )
        )
    )
    assert result["status"] == "ran"
    assert result["jev_relevance"]["sell_shock"] == 0.75
    assert len(relevance_calls) == 1
    assert len(judge_calls) == len(SCENARIOS)

    lines = (tmp_path / "trust_ledger.jsonl").read_text().strip().splitlines()
    recs = [json.loads(line) for line in lines]
    assert all(r["jev_relevance"] == 0.75 for r in recs)
    assert all(r["alignment"]["jev_judge_score"] == 0.6 for r in recs)
    assert all(r["tickers"] == ["SPY", "AAPL", "QQQ", "IWM"] for r in recs)

    latest = json.loads((tmp_path / "latest_market_run.json").read_text())
    assert latest["jev_relevance"]["sell_shock"] == 0.75
    assert "weak signal" in latest["jev_note"]


def test_accumulate_jev_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("JEV_ENABLED", raising=False)
    result = asyncio.run(accumulate_week(**_accum_kwargs(tmp_path)))
    assert result["status"] == "ran"
    assert result["jev_relevance"] == {}
    lines = (tmp_path / "trust_ledger.jsonl").read_text().strip().splitlines()
    recs = [json.loads(line) for line in lines]
    assert all(r["jev_relevance"] is None for r in recs)
    assert all(r["alignment"]["jev_judge_score"] is None for r in recs)
    latest = json.loads((tmp_path / "latest_market_run.json").read_text())
    assert latest["jev_relevance"] == {}
    assert "jev_note" not in latest


def test_accumulate_jev_fail_soft_end_to_end(tmp_path):
    def boom(state):
        raise RuntimeError("api down")

    result = asyncio.run(
        accumulate_week(
            **_accum_kwargs(tmp_path, jev=True, score_relevance_fn=boom)
        )
    )
    # scoring failure must not fail the run
    assert result["status"] == "ran"
    assert result["n_records"] == len(SCENARIOS)
