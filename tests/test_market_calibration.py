"""Tests for the MSM calibration harness (Phase 5).

Deterministic unit tests for the objective and moment computation, the
prereg schema, and the structural holdout guard. The optimizer itself is
exercised on a cheap toy objective, not the simulator.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from eve_miro.core.calibration import (
    PARAM_NAMES,
    PARAM_SPECS,
    CalibrationParams,
    build_agents,
    degeneracy_report,
    load_fit_targets,
    make_objective,
    nelder_mead,
    simulate_daily_closes,
)
from eve_miro.core.calibration.moments import (
    abs_return_autocorr,
    compute_moments,
    hill_tail_index,
    log_returns,
    percentiles,
    rolling_std,
)
from eve_miro.core.calibration.optimize import OptimizeResult
from eve_miro.paths import REPO_ROOT

PREREG_PATH = REPO_ROOT / "experiments" / "market" / "calibration_prereg.json"
TARGETS_PATH = Path("/home/hatch/workspace/eve-miro-research/calibration/targets_fit.json")

requires_targets = pytest.mark.skipif(
    not TARGETS_PATH.is_file(), reason="research calibration targets not present"
)


# -- prereg schema --------------------------------------------------------


def test_prereg_frozen_and_complete():
    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    assert prereg["frozen"] is True
    assert prereg["method"] == "simulated_method_of_moments"
    assert len(prereg["parameters"]) == 9
    assert len(prereg["moments"]) == 16
    for spec in prereg["parameters"]:
        assert spec["bound"][0] < spec["start"] < spec["bound"][1], spec["name"]
    for moment in prereg["moments"]:
        assert {"key", "scale", "weight"} <= set(moment)


def test_prereg_params_match_code():
    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    assert [s["name"] for s in prereg["parameters"]] == list(PARAM_NAMES)
    for spec, code in zip(prereg["parameters"], PARAM_SPECS):
        assert spec["bound"][0] == code.lo
        assert spec["bound"][1] == code.hi
        assert spec["start"] == code.start


# -- parameter vector -----------------------------------------------------


def test_param_unit_roundtrip():
    p = CalibrationParams.starting_point()
    u = p.to_unit()
    q = CalibrationParams.from_unit(u)
    for a, b in zip(p.values, q.values):
        assert abs(a - b) < 1e-6, (a, b)


def test_param_bounds_enforced():
    with pytest.raises(ValueError):
        CalibrationParams((200.0,) + tuple(s.start for s in PARAM_SPECS[1:]))


def test_param_missing_key():
    with pytest.raises(ValueError):
        CalibrationParams.from_dict({"mm_spread_bps": 10.0})


def test_agent_counts_guarantees():
    for frac in (0.5, 0.85, 0.95):
        d = dict(CalibrationParams.starting_point().to_dict())
        d["noise_frac"] = frac
        p = CalibrationParams.from_dict(d)
        counts = p.agent_counts(32)
        assert sum(counts.values()) == 32
        assert counts["market_maker"] >= 1
        assert counts["momentum"] >= 1
        assert counts["fundamental"] >= 1
        assert counts["noise"] >= 1


def test_integer_param_rounds():
    p = CalibrationParams.from_unit([0.0] * len(PARAM_SPECS))
    assert isinstance(p.momentum_kwargs()["lookback"], int)


def test_build_agents_kinds():
    agents = build_agents(CalibrationParams.starting_point(), "ACME", seed=1, total=32)
    kinds = sorted(a.kind for a in agents)
    assert "market_maker" in kinds and "noise" in kinds
    assert "momentum" in kinds and "fundamental" in kinds
    assert len(agents) == 32


# -- lean runner ----------------------------------------------------------


def test_runner_returns_requested_closes():
    closes = simulate_daily_closes(
        CalibrationParams.starting_point(), days=30, seed=11, total_agents=8
    )
    assert len(closes) == 30
    assert all(c > 0 for c in closes)


def test_runner_deterministic():
    p = CalibrationParams.starting_point()
    a = simulate_daily_closes(p, days=30, seed=11, total_agents=8)
    b = simulate_daily_closes(p, days=30, seed=11, total_agents=8)
    assert a == b


def test_runner_seeds_differ():
    p = CalibrationParams.starting_point()
    a = simulate_daily_closes(p, days=30, seed=11, total_agents=8)
    b = simulate_daily_closes(p, days=30, seed=12, total_agents=8)
    assert a != b


def test_runner_fail_closed():
    p = CalibrationParams.starting_point()
    with pytest.raises(ValueError):
        simulate_daily_closes(p, days=0, seed=1)
    with pytest.raises(ValueError):
        simulate_daily_closes(p, days=10, warmup_days=10, seed=1)
    with pytest.raises(ValueError):
        simulate_daily_closes(p, days=10, seed=1, initial_price=-5.0)


# -- moments --------------------------------------------------------------


def test_log_returns_rejects_nonpositive():
    with pytest.raises(ValueError):
        log_returns(np.array([100.0, 0.0, 101.0]))


def test_rolling_std_matches_pandas_semantics():
    rng = np.random.default_rng(3)
    x = rng.normal(size=50)
    out = rolling_std(x, 5)
    assert np.isnan(out[:4]).all()
    seg = x[:5]
    assert abs(out[4] - np.std(seg, ddof=1)) < 1e-12


def test_abs_return_autocorr_perfect():
    x = np.array([0.01, -0.01] * 20)
    assert abs(abs_return_autocorr(x, 2) - 1.0) < 1e-12


def test_hill_tail_index_positive():
    rng = np.random.default_rng(4)
    x = rng.standard_t(3, size=2000)
    alpha = hill_tail_index(x, "right")
    assert 2.0 < alpha < 4.5  # t(3) has tail index 3


def test_percentiles_rejects_empty():
    with pytest.raises(ValueError):
        percentiles(np.array([]))


def test_compute_moments_keys():
    rng = np.random.default_rng(5)
    reps = [100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, 40))) for _ in range(2)]
    m = compute_moments([np.asarray(r) for r in reps])
    for key in (
        "log_return.std", "log_return.excess_kurtosis", "log_return.skew",
        "abs_return_autocorr.lag1", "abs_return_autocorr.lag20",
        "realized_vol_annualized.rv5.mean", "realized_vol_annualized.rv20.std",
        "hill_tail_index.left_5pct", "hill_tail_index.right_5pct", "log_return.mean",
    ):
        assert key in m and math.isfinite(m[key]), key


def test_compute_moments_needs_length():
    with pytest.raises(ValueError):
        compute_moments([np.ones(10)])


# -- targets / structural holdout guard -----------------------------------


@requires_targets
def test_load_fit_targets_strips_holdout():
    loaded = load_fit_targets(TARGETS_PATH)
    assert set(loaded["tickers"]) == {"AAPL", "SPY"}
    for ticker, entry in loaded["tickers"].items():
        assert not any("holdout" in k.lower() for k in entry), ticker


@requires_targets
def test_load_fit_targets_refuses_holdout_stats(tmp_path):
    raw = json.loads(TARGETS_PATH.read_text(encoding="utf-8"))
    raw["SPY"]["holdout_mean_return"] = 0.001
    p = tmp_path / "targets.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="holdout"):
        load_fit_targets(p)


def test_load_fit_targets_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_fit_targets(tmp_path / "nope.json")


def test_load_fit_targets_missing_block(tmp_path):
    p = tmp_path / "targets.json"
    p.write_text(json.dumps({"SPY": {"log_return": {}}}), encoding="utf-8")
    with pytest.raises(ValueError, match="realized_vol_annualized"):
        load_fit_targets(p)


# -- objective ------------------------------------------------------------


@requires_targets
def test_objective_deterministic():
    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    targets = load_fit_targets(TARGETS_PATH)
    obj = make_objective(prereg, targets)
    u = np.array(CalibrationParams.starting_point().to_unit())
    assert obj(u) == obj(u)


@requires_targets
def test_objective_rejects_unknown_ticker():
    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    targets = load_fit_targets(TARGETS_PATH)
    with pytest.raises(ValueError, match="not in targets"):
        make_objective(prereg, targets, ticker="NOPE")


@requires_targets
def test_objective_moment_keys_complete():
    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    targets = load_fit_targets(TARGETS_PATH)
    obj = make_objective(prereg, targets)
    res = obj.evaluate(CalibrationParams.starting_point())
    assert set(res["errors"]) == {s["key"] for s in prereg["moments"]}
    assert res["value"] >= 0 and math.isfinite(res["value"])


# -- optimizer on a toy objective -----------------------------------------


def test_nelder_mead_toy_quadratic():
    # Driver mechanics test on a tractable 9-d quadratic: starts near the
    # answer so Nelder-Mead converges within budget. (Nelder-Mead is known
    # to stall on far-start smooth quadratics via simplex collapse; that is
    # an algorithm property, not a driver defect.)
    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    prereg = dict(prereg)
    prereg["optimizer"] = {"xatol": 0.01, "fatol": 0.0001, "max_evaluations": 1000}
    target = np.full(len(PARAM_SPECS), 0.7)
    x0 = np.full(len(PARAM_SPECS), 0.5)
    initial = float(np.sum((x0 - target) ** 2))
    res = nelder_mead(lambda u: float(np.sum((u - target) ** 2)), x0, prereg)
    assert res.value < initial / 100, (res.value, initial)
    assert isinstance(res.params, CalibrationParams)
    assert res.n_evaluations > 0


def test_nelder_mead_rejects_bad_x0():
    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    with pytest.raises(ValueError):
        nelder_mead(lambda u: 1.0, np.zeros(3), prereg)


def test_degeneracy_report_flags():
    def mk(vals, value):
        return OptimizeResult(
            params=CalibrationParams.from_unit(vals), value=value,
            n_evaluations=10, converged=True,
        )

    dim = len(PARAM_SPECS)
    # Same objective, far-apart parameters: degenerate.
    rep = degeneracy_report([mk(np.full(dim, -1.0), 1.0), mk(np.full(dim, 1.0), 1.02)])
    assert rep["degenerate"] is True
    # Clearly different objectives: not degenerate.
    rep2 = degeneracy_report([mk(np.full(dim, -1.0), 1.0), mk(np.full(dim, 1.0), 2.0)])
    assert rep2["degenerate"] is False
    # Pairwise degeneracy: two starts agree within 10% with different
    # parameters even though a third start found a better basin.
    rep3 = degeneracy_report([
        mk(np.full(dim, -1.0), 5.39),
        mk(np.full(dim, 1.0), 5.86),
        mk(np.zeros(dim), 3.71),
    ])
    assert rep3["degenerate"] is True
    assert rep3["degenerate_pairs"][0]["starts"] == [0, 1]
    assert rep3["best_index"] == 2


def test_degeneracy_report_needs_results():
    with pytest.raises(ValueError):
        degeneracy_report([])
