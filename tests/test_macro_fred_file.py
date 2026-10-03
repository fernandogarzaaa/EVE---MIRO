"""FRED macro provider reading pre-fetched observations from FRED_MACRO_JSON."""

from __future__ import annotations

import json

import pytest

from eve_miro.cli.market_accumulate import fetch_macro
from eve_miro.config import TimeWindow
from eve_miro.errors import ProviderError
from eve_miro.providers import macro_fred
from eve_miro.providers.macro_fred import MacroFREDProvider, read_file_payload

GOOD = {
    "DGS10": [
        {"date": "2026-10-01", "value": "5.24"},
        {"date": "2026-09-30", "value": "5.29"},
    ],
    "UNRATE": [{"date": "2026-09-01", "value": "4.1"}],
}


def _write(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")
    return str(path)


def _window():
    return TimeWindow(start="2026-09-01", end="2026-10-02")


def test_read_file_payload_parses_schema(tmp_path):
    payload = read_file_payload(_write(tmp_path / "macro.json", GOOD))
    series = payload["series"]
    assert set(series) == {"DGS10", "UNRATE"}
    assert series["DGS10"]["title"] == "10-Year Treasury Constant Maturity Rate"
    assert series["DGS10"]["units"] == "percent"
    assert series["DGS10"]["observations"][0] == {"date": "2026-10-01", "value": "5.24"}


def test_read_file_payload_unknown_series_kept(tmp_path):
    payload = read_file_payload(_write(tmp_path / "macro.json", {"WIKIALPHA": [{"date": "2026-10-01", "value": 1.5}]}))
    assert payload["series"]["WIKIALPHA"]["observations"][0]["value"] == 1.5


@pytest.mark.parametrize(
    "bad",
    [
        "{not json",
        [],
        {},
        {"DGS10": []},
        {"DGS10": [{"date": "2026-10-01"}]},
        {"DGS10": [{"value": "5.24"}]},
        {"DGS10": ["nope"]},
        {"": [{"date": "2026-10-01", "value": "5.24"}]},
    ],
)
def test_read_file_payload_rejects_corrupt(tmp_path, bad):
    path = tmp_path / "macro.json"
    if isinstance(bad, str) and bad.startswith("{not"):
        path.write_text(bad, encoding="utf-8")
    else:
        _write(path, bad)
    with pytest.raises(ValueError):
        read_file_payload(str(path))


def test_read_file_payload_missing_file_raises(tmp_path):
    with pytest.raises(ValueError):
        read_file_payload(str(tmp_path / "absent.json"))


async def test_provider_fetch_uses_file(tmp_path, monkeypatch):
    monkeypatch.setenv(macro_fred.FILE_ENV, _write(tmp_path / "macro.json", GOOD))
    events = await MacroFREDProvider().fetch(_window())
    assert events, "expected macro events from the file"
    by_id = {e.id: e for e in events}
    assert by_id["macro_fred:DGS10:20261001"].payload["value"] == 5.24
    assert by_id["macro_fred:DGS10:20261001"].payload["date"] == "2026-10-01"
    assert by_id["macro_fred:UNRATE:20260901"].payload["value"] == 4.1
    assert all(e.source.provider == "macro_fred" for e in events)


async def test_provider_fetch_corrupt_file_raises(tmp_path, monkeypatch):
    path = tmp_path / "macro.json"
    path.write_text("{broken", encoding="utf-8")
    monkeypatch.setenv(macro_fred.FILE_ENV, str(path))
    with pytest.raises(ProviderError):
        await MacroFREDProvider().fetch(_window())


async def test_fetch_macro_prefers_file_over_api(tmp_path, monkeypatch):
    monkeypatch.setenv(macro_fred.FILE_ENV, _write(tmp_path / "macro.json", GOOD))
    monkeypatch.setenv("FRED_API_KEY", "should-not-be-used")

    async def boom():
        raise AssertionError("API must not be called when the file is set")

    monkeypatch.setattr(macro_fred, "_live_payload", boom)
    macro = await fetch_macro()
    assert macro["DGS10"] == {"date": "2026-10-01", "value": "5.24"}
    assert macro["UNRATE"] == {"date": "2026-09-01", "value": "4.1"}


async def test_fetch_macro_corrupt_file_soft_skips(tmp_path, monkeypatch, capsys):
    path = tmp_path / "macro.json"
    path.write_text("{broken", encoding="utf-8")
    monkeypatch.setenv(macro_fred.FILE_ENV, str(path))
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert await fetch_macro() is None
    assert "warn" in capsys.readouterr().out


async def test_fetch_macro_neither_set_skips(monkeypatch):
    monkeypatch.delenv(macro_fred.FILE_ENV, raising=False)
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert await fetch_macro() is None
