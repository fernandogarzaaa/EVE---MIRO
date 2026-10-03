"""Offline tests for `eve-miro market-sim` (Phase 4).

Runs the full fixture-grounded market loop: fixture bars -> t0/t1 split ->
market snapshot -> marketsim scenario -> alignment -> ledger trust.
Asserts exit code 0 and that the trust summary names the scenario class.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import pytest

from eve_miro.cli.market_sim import SUMMARY_PATH, cmd_market_sim
from eve_miro.cli.main import COMMANDS, main


def _run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(io.StringIO()):
        rc = cmd_market_sim(argv)
    return rc, buf.getvalue()


def test_market_sim_happy_path_sell_shock():
    rc, out = _run(["--scenario", "sell_shock_001", "--hours", "72"])
    assert rc == 0, out
    assert "sell_shock" in out
    assert "aggregate alignment score" in out
    assert "scenario-class trust" in out
    assert "SIMULATED" in out
    assert SUMMARY_PATH.is_file()
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    assert summary["scenario"] == "sell_shock_001"
    assert summary["alignment"]["scenario_class"] == "sell_shock"
    assert "sell_shock" in summary["trust"]
    assert summary["trust"]["sell_shock"]["n_alignments"] >= 1
    assert "describe" in summary["trust"]["sell_shock"]


def test_market_sim_vol_spike_and_rate_shock():
    for name, sclass in (("vol_spike_001", "volatility_spike"), ("rate_shock_001", "rate_shock")):
        rc, out = _run(["--scenario", name, "--hours", "72"])
        assert rc == 0, out
        assert sclass in out


def test_market_sim_rejects_short_horizon():
    rc, _out = _run(["--scenario", "sell_shock_001", "--hours", "48"])
    assert rc != 0


def test_market_sim_fail_closed_missing_fixture(tmp_path: Path):
    rc, _out = _run(
        ["--scenario", "sell_shock_001", "--hours", "72", "--fixture-dir", str(tmp_path)]
    )
    assert rc != 0


def test_market_sim_unknown_scenario_rejected():
    with pytest.raises(SystemExit):
        _run(["--scenario", "nope_001"])


def test_market_sim_registered_in_cli():
    assert COMMANDS["market-sim"] is not None
    buf = io.StringIO()
    with redirect_stdout(buf):
        with pytest.raises(SystemExit) as exc:
            main(["market-sim", "--help"])
    assert exc.value.code == 0
    assert "--scenario" in buf.getvalue()
