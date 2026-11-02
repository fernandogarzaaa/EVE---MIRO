"""CLI tests for eve-miro funnel-sim (offline, fixtures only)."""

from __future__ import annotations

import json

import pytest
import yaml

from eve_miro.cli.funnel_sim import (
    SCENARIOS,
    cmd_funnel_sim,
    list_scenarios,
    run_funnel_scenario,
)
from eve_miro.paths import REPO_ROOT


def test_registry_lists_all_four_yaml_scenarios():
    assert set(SCENARIOS) == {
        "funnel_base_001",
        "funnel_pessimistic_001",
        "funnel_optimistic_001",
        "funnel_speed_to_lead_001",
    }
    assert list_scenarios() == sorted(SCENARIOS)


def test_registry_only_picks_type_funnel(tmp_path, monkeypatch):
    import eve_miro.cli.funnel_sim as cli

    d = tmp_path / "experiments" / "funnel"
    d.mkdir(parents=True)
    (d / "a.yaml").write_text(yaml.safe_dump({"name": "a", "type": "funnel"}), encoding="utf-8")
    (d / "b.yaml").write_text(yaml.safe_dump({"name": "b", "type": "market"}), encoding="utf-8")
    (d / "broken.yaml").write_text("not: [valid", encoding="utf-8")
    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
    assert cli.list_scenarios() == ["a"]


def test_unknown_scenario_raises_value_error():
    with pytest.raises(ValueError, match="unknown scenario"):
        run_funnel_scenario("nope", 1)


def test_zero_months_raises_value_error():
    with pytest.raises(ValueError, match="months must be at least"):
        run_funnel_scenario("funnel_base_001", 0)


def test_missing_fixture_dir_fails_closed(tmp_path):
    with pytest.raises(FileNotFoundError, match="missing fixture"):
        run_funnel_scenario("funnel_base_001", 1, fixture_dir=tmp_path / "absent")


def test_end_to_end_offline_one_month():
    summary = run_funnel_scenario("funnel_base_001", 1)
    assert summary["scenario"] == "funnel_base_001"
    assert summary["months"] == 1
    assert summary["mode"] == "post_job"
    assert summary["ledger_verdict"] == "PENDING"
    m = summary["metrics"]
    assert m["jobs"] > 0
    assert m["reviews_gained"] > 0
    assert m["cost"] > 0
    assert "SIMULATED" in summary["disclaimer"]
    for key in ("reviews_per_100", "problems_routed", "cost", "revenue", "opt_out_rate"):
        assert key in summary["mean_series"]
        assert len(summary["mean_series"][key]) == 30


def test_speed_to_lead_scenario_runs():
    summary = run_funnel_scenario("funnel_speed_to_lead_001", 1)
    assert summary["mode"] == "speed_to_lead"
    assert summary["metrics"]["bookings"] > 0
    assert "bookings_per_100_leads" in summary["mean_series"]


def test_cmd_writes_summary_file(tmp_path, monkeypatch):
    import eve_miro.cli.funnel_sim as cli

    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
    # Point the fixture + scenario dirs at the real repo via symlinks.
    (tmp_path / "experiments").symlink_to(REPO_ROOT / "experiments", target_is_directory=True)
    (tmp_path / "datasets").symlink_to(REPO_ROOT / "datasets", target_is_directory=True)
    rc = cmd_funnel_sim(["--scenario", "funnel_base_001", "--months", "1"])
    assert rc == 0
    out = tmp_path / "storage" / "funnel" / "latest_funnel_run.json"
    assert out.is_file()
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["scenario"] == "funnel_base_001"


def test_cmd_rejects_unknown_scenario_choice():
    with pytest.raises(SystemExit):
        cmd_funnel_sim(["--scenario", "nope", "--months", "1"])
