"""Jev (TypeSafe) weak-signal scoring for the weekly accumulation run.

Standing rules, carried over from Signal Lab: Jev is a scalable weak
signal, NOT gold. Scores are recorded for attention and context only;
the empirical per-class trust computation never ingests them. Scoring
is opt-in via ``JEV_ENABLED=1`` and fails soft everywhere: no key,
missing credential helper, API error, or timeout means skip scoring
with a logged note, never fail the run.

Two questions:
- relevance: after the weekly run grounds the market state, one typed
  score question per scenario class rating how relevant it is to
  stress-test that class this week. Drives weighting and attention in
  the report, never prediction.
- judge: after numeric alignment, one score question per scenario asking
  whether the simulated path captures the realized stress character.
  Stored as a separate weak-signal field on the alignment record.
"""

from __future__ import annotations

import json
import math
import os
import sys
import urllib.error
import urllib.request
from typing import Any

JEV_ENABLED_ENV = "JEV_ENABLED"
JEV_HOST = "api.typesafe.ai"
JEV_BASE = f"https://{JEV_HOST}/v1"
JEV_MODEL = "jev-latest"
JEV_CREDENTIAL = "custom.typesafe"
JEV_TIMEOUT = 30

# Scenario classes that get a relevance question. Mirrors
# eve_miro.core.reality.trust_profile.SCENARIO_CLASSES minus "baseline"
# (baseline is not a stress-test class).
RELEVANCE_CLASSES = (
    "sell_shock",
    "volatility_spike",
    "rate_shock",
    "earn_gap_down",
    "earn_gap_snapback",
    "sector_flash",
    "macro_slide",
)

_CLASS_BLURB = {
    "sell_shock": "broad market selloff with sustained liquidation pressure",
    "volatility_spike": "abrupt volatility expansion without a directional crash",
    "rate_shock": "interest-rate repricing that hits duration and growth assets",
    "earn_gap_down": "earnings disaster with permanent impairment, no snapback",
    "earn_gap_snapback": "earnings shock that V-recovers as fundamentals hold",
    "sector_flash": "single-session sector-wide liquidation, then flat",
    "macro_slide": "multi-day macro-driven grind lower in escalating waves",
}

RELEVANCE_CRITERIA: dict[str, list[str]] = {
    sclass: [
        f"not relevant: calm orderly market, no sign of {_CLASS_BLURB[sclass]}",
        f"mildly relevant: some chop, {_CLASS_BLURB[sclass]} not visible",
        f"relevant: elevated stress consistent with {_CLASS_BLURB[sclass]}",
        f"highly relevant: active conditions matching {_CLASS_BLURB[sclass]}",
    ]
    for sclass in RELEVANCE_CLASSES
}

JUDGE_CRITERIA = [
    "no resemblance: the simulated path misses the realized stress entirely",
    "weak resemblance: direction roughly right, stress character off",
    "good resemblance: captures the realized stress character with minor differences",
    "strong resemblance: the stress character is closely reproduced",
]

JEV_NOTE = (
    "Jev scores are a weak signal for attention only, not evidence. "
    "Trust scores come from the empirical alignment ledger."
)


def jev_enabled() -> bool:
    """Opt-in gate: scoring only runs when JEV_ENABLED=1."""
    return (os.environ.get(JEV_ENABLED_ENV) or "").strip() == "1"


def _post_decide(
    state: str, questions: dict[str, dict[str, Any]], timeout: int = JEV_TIMEOUT
) -> dict[str, Any] | None:
    """POST one batched decide call. Fail soft: None on any problem."""
    try:
        sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
        from dynamic_credentials import (  # noqa: E402
            add_surrogate_to_request,
            read_json_response,
        )
    except ImportError as exc:
        print(f"note: Jev scoring skipped (credential helper missing: {exc})")
        return None
    payload = {"model": JEV_MODEL, "state": state, "questions": questions}
    req = urllib.request.Request(
        JEV_BASE + "/systemone",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        add_surrogate_to_request(
            req, JEV_CREDENTIAL, allowed_hosts=[JEV_HOST]
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return read_json_response(resp)
    except Exception as exc:
        print(f"note: Jev scoring skipped (API error: {exc})")
        return None


def _score_answer(answer: dict[str, Any]) -> float | None:
    """Normalize a Jev score answer to 0..1. None when unparseable."""
    if not isinstance(answer, dict):
        return None
    raw = answer.get("score")
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        return None
    legend = answer.get("legend") or {}
    n_levels = len(legend) if isinstance(legend, dict) and legend else 4
    span = max(n_levels - 1, 1)
    return max(0.0, min(1.0, float(raw) / span))


def build_market_state(
    bars: list[dict[str, Any]], vix: float | None, window: int = 20
) -> dict[str, Any]:
    """Summarize grounded bars into the state Jev relevance questions read.

    Per ticker: trailing-window realized vol (std of log returns), maximum
    drawdown, and window trend. Pure arithmetic on the fetched bars.
    """
    by_ticker: dict[str, list[float]] = {}
    for bar in bars:
        ticker = str(bar.get("ticker"))
        close = bar.get("close")
        if isinstance(close, (int, float)) and close > 0:
            by_ticker.setdefault(ticker, []).append(float(close))
    tickers: dict[str, dict[str, float | None]] = {}
    for ticker in sorted(by_ticker):
        closes = by_ticker[ticker][-window:]
        rets = [
            math.log(closes[i] / closes[i - 1])
            for i in range(1, len(closes))
            if closes[i - 1] > 0
        ]
        vol = (
            math.sqrt(sum((r - sum(rets) / len(rets)) ** 2 for r in rets) / len(rets))
            if len(rets) > 1
            else None
        )
        peak = closes[0]
        max_dd = 0.0
        for c in closes:
            peak = max(peak, c)
            max_dd = min(max_dd, c / peak - 1.0)
        trend = closes[-1] / closes[0] - 1.0 if closes[0] > 0 else None
        tickers[ticker] = {
            "trailing_vol": vol,
            "max_drawdown": max_dd,
            "trend": trend,
        }
    return {"vix": vix, "window_days": window, "tickers": tickers}


def render_market_state(state: dict[str, Any]) -> str:
    """Render the market state dict as the text of a Jev state."""
    lines = []
    vix = state.get("vix")
    lines.append(
        f"Current market snapshot. VIX: "
        f"{vix:.1f}" if isinstance(vix, (int, float)) else "VIX: unavailable"
    )
    for ticker, stats in (state.get("tickers") or {}).items():
        vol = stats.get("trailing_vol")
        dd = stats.get("max_drawdown")
        trend = stats.get("trend")
        lines.append(
            f"{ticker}: trailing {state.get('window_days', 20)}d vol "
            f"{vol:.4f}" if isinstance(vol, float) else f"{ticker}: vol n/a"
        )
        lines[-1] += (
            f", max drawdown {dd:.1%}, trend {trend:+.1%}"
            if isinstance(dd, float) and isinstance(trend, float)
            else ", drawdown/trend n/a"
        )
    return "\n".join(lines)


def score_scenario_relevance(
    market_state: dict[str, Any],
    classes: tuple[str, ...] = RELEVANCE_CLASSES,
) -> dict[str, float | None] | None:
    """Rate each scenario class's stress-test relevance this week.

    One batched Jev call with one score question per class. Returns
    {scenario_class: normalized 0..1 score} or None when scoring is
    disabled or unavailable. Never raises.
    """
    if not jev_enabled():
        return None
    state = render_market_state(market_state)
    questions = {
        f"relevance_{sclass}": {
            "type": "score",
            "instructions": (
                "Rate how relevant it is to stress-test a "
                f"{_CLASS_BLURB[sclass]} scenario this week, given the "
                "market snapshot. This informs which stress tests deserve "
                "attention; it is not a market prediction."
            ),
            "criteria": RELEVANCE_CRITERIA[sclass],
        }
        for sclass in classes
        if sclass in RELEVANCE_CRITERIA
    }
    if not questions:
        return None
    try:
        resp = _post_decide(state, questions)
    except Exception as exc:  # fail soft even on unexpected errors
        print(f"note: Jev relevance scoring skipped ({exc})")
        return None
    if not resp:
        return None
    answers = resp.get("answers") or {}
    out: dict[str, float | None] = {}
    for sclass in classes:
        if sclass not in RELEVANCE_CRITERIA:
            continue
        out[sclass] = _score_answer(answers.get(f"relevance_{sclass}") or {})
    return out


def judge_alignment(sim_text: str, realized_text: str) -> float | None:
    """Ask Jev whether the simulated path captures the realized stress.

    Returns a normalized 0..1 score or None when disabled/unavailable.
    Never raises. Weak signal only: stored on the alignment record, never
    fed into trust.
    """
    if not jev_enabled():
        return None
    state = (
        "Simulated stress path:\n" + sim_text + "\n\nRealized market path:\n" + realized_text
    )
    try:
        resp = _post_decide(
            state,
            {
                "judge": {
                    "type": "score",
                    "instructions": (
                        "Does the simulated path capture the character of "
                        "the realized market stress (shape, depth, "
                        "recovery)? Judge resemblance of stress character, "
                        "not exact prices."
                    ),
                    "criteria": JUDGE_CRITERIA,
                }
            },
        )
    except Exception as exc:
        print(f"note: Jev alignment judging skipped ({exc})")
        return None
    if not resp:
        return None
    return _score_answer((resp.get("answers") or {}).get("judge") or {})
