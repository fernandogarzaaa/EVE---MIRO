"""Market snapshot: folds market.* WorldEvents into Economy.indicators['market_snapshot'].

Pure function over OBSERVED events; never invents values. Missing data yields
missing keys, not defaults.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Iterable

from eve_miro.core.world.events import WorldEvent
from eve_miro.core.world.temporal import as_utc

TRADING_DAYS = 252


def _log_returns(closes: list[float]) -> list[float]:
    out = []
    for prev, cur in zip(closes, closes[1:]):
        if prev and prev > 0 and cur and cur > 0:
            out.append(math.log(cur / prev))
    return out


def _realized_vol(logrets: list[float]) -> float | None:
    if len(logrets) < 2:
        return None
    mean = sum(logrets) / len(logrets)
    var = sum((r - mean) ** 2 for r in logrets) / (len(logrets) - 1)
    return math.sqrt(var * TRADING_DAYS)


def _pct_change(closes: list[float], lag: int) -> float | None:
    if len(closes) <= lag:
        return None
    base, last = closes[-(lag + 1)], closes[-1]
    if not base:
        return None
    return last / base - 1.0


def build_market_snapshot(events: Iterable[WorldEvent]) -> dict:
    bars: dict[str, list[tuple[datetime, float]]] = {}
    contracts: dict[str, list[dict]] = {}
    vix_rows: list[tuple[datetime, float]] = []
    macro: dict[str, list[tuple[datetime, float]]] = {}
    news: list[dict] = []
    ref_time = datetime(1970, 1, 1, tzinfo=timezone.utc)

    for event in events:
        et = event.event_type
        payload = event.payload or {}
        eff = as_utc(event.temporal.effective_time)
        if eff > ref_time:
            ref_time = eff
        if et == "market.bar":
            if payload.get("interval") != "1d":
                continue
            ticker = payload.get("ticker")
            close = payload.get("close")
            if not ticker or not isinstance(close, (int, float)):
                continue
            bars.setdefault(ticker, []).append((as_utc(event.temporal.effective_time), float(close)))
        elif et == "market.options_chain":
            ticker = payload.get("ticker")
            if ticker:
                contracts.setdefault(ticker, []).append(payload)
        elif et == "market.iv_index":
            vix = payload.get("vix")
            if isinstance(vix, (int, float)):
                vix_rows.append((as_utc(event.temporal.effective_time), float(vix)))
        elif et == "market.macro":
            series_id = payload.get("series_id")
            value = payload.get("value")
            if series_id and isinstance(value, (int, float)):
                macro.setdefault(series_id, []).append((as_utc(event.temporal.effective_time), float(value)))
        elif et == "market.news":
            news.append(
                {
                    "time": as_utc(event.temporal.effective_time).isoformat(),
                    "title": payload.get("title"),
                    "url": payload.get("url"),
                }
            )

    tickers: dict[str, dict] = {}
    for ticker, rows in bars.items():
        rows.sort(key=lambda r: r[0])
        closes = [c for _, c in rows]
        logrets = _log_returns(closes)
        tickers[ticker] = {
            "latest_close": closes[-1],
            "latest_time": rows[-1][0].isoformat(),
            "bars_n": len(rows),
            "return_1d": _pct_change(closes, 1),
            "return_5d": _pct_change(closes, 5),
            "return_20d": _pct_change(closes, 20),
            "realized_vol_5d": _realized_vol(logrets[-5:]),
            "realized_vol_20d": _realized_vol(logrets[-20:]),
        }

    iv_summary: dict[str, dict] = {}
    for ticker, rows in contracts.items():
        near, mid = [], []
        put_oi = call_oi = 0.0
        for c in rows:
            iv = c.get("implied_volatility")
            expiry_raw = c.get("expiry")
            try:
                expiry = as_utc(expiry_raw) if expiry_raw else None
            except (ValueError, TypeError):
                expiry = None
            oi = c.get("open_interest") or 0.0
            if c.get("option_type") == "put":
                put_oi += oi
            else:
                call_oi += oi
            if iv is None or expiry is None:
                continue
            dte = (expiry.date() - ref_time.date()).days
            if dte <= 45:
                near.append(float(iv))
            elif dte <= 120:
                mid.append(float(iv))
        summary: dict = {
            "contracts_n": len(rows),
            "put_call_oi_ratio": (put_oi / call_oi) if call_oi else None,
        }
        if near:
            summary["iv_near_term_mean"] = sum(near) / len(near)
        if mid:
            summary["iv_mid_term_mean"] = sum(mid) / len(mid)
        if ticker in tickers:
            tickers[ticker]["options"] = summary
        else:
            iv_summary[ticker] = summary

    vix_rows.sort(key=lambda r: r[0])
    macro_latest = {sid: {"value": rows[-1][1], "time": rows[-1][0].isoformat()} for sid, rows in macro.items() if rows}
    news.sort(key=lambda n: n["time"])

    snapshot: dict = {
        "tickers": tickers,
        "vix": {"latest": vix_rows[-1][1], "time": vix_rows[-1][0].isoformat()} if vix_rows else None,
        "macro": macro_latest,
        "news": {"count": len(news), "latest": news[-5:]},
    }
    if iv_summary:
        snapshot["iv_unmatched"] = iv_summary
    return snapshot
