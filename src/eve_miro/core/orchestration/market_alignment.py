"""Market alignment: SIMULATED market trajectories vs OBSERVED t1.

Per ticker we compare the simulated price path against the observed
``market.bar`` close series over the same horizon:

- return-distribution comparison via the two-sample Kolmogorov-Smirnov test
- realized-vol path comparison (rolling vol, simulated vs observed)
- max-drawdown depth comparison (absolute difference)

Per-metric values plus an aggregate alignment score in [0, 1]
(1.0 = identical series) are reported on the MarketAlignment record.

Honest limits: alignment measures calibration of a scenario class against
one realized path, not predictive power. Exogenous news is unmodeled, the
realized path is a single draw, and a high score means the scenario
behaved like this realization, not that the simulator predicts markets.
"""

from __future__ import annotations

import math
from typing import Sequence

from pydantic import BaseModel, Field

from eve_miro.core.reality.ledger import RealityLedger
from eve_miro.core.world.events import ProvenanceKind, WorldEvent
from eve_miro.core.world.temporal import iso

TRADING_DAYS = 252

SCENARIO_CLASSES = (
    "sell_shock",
    "volatility_spike",
    "rate_shock",
    "earn_gap_down",
    "earn_gap_snapback",
    "sector_flash",
    "macro_slide",
    "baseline",
)


def scenario_class_for(scenario_id: str) -> str:
    """Map a scenario id to its calibration class. Unknown ids are baseline."""
    sid = (scenario_id or "").lower()
    if "earn_gap_down" in sid:
        return "earn_gap_down"
    if "earn_gap_snapback" in sid:
        return "earn_gap_snapback"
    if "sector_flash" in sid:
        return "sector_flash"
    if "macro_slide" in sid:
        return "macro_slide"
    if "sell_shock" in sid or "sellshock" in sid:
        return "sell_shock"
    if "vol_spike" in sid or "volatility_spike" in sid or "volatility" in sid:
        return "volatility_spike"
    if "rate_shock" in sid or "rateshock" in sid:
        return "rate_shock"
    return "baseline"


def log_returns(prices: Sequence[float]) -> list[float]:
    out: list[float] = []
    for prev, cur in zip(prices, prices[1:]):
        if prev and prev > 0 and cur and cur > 0:
            out.append(math.log(cur / prev))
    return out


def max_drawdown(prices: Sequence[float]) -> float:
    """Most negative peak-to-trough move as a fraction (0.0 = no drawdown)."""
    peak = -math.inf
    worst = 0.0
    for m in prices:
        peak = max(peak, float(m))
        if peak > 0:
            worst = min(worst, float(m) / peak - 1.0)
    return worst if math.isfinite(worst) else 0.0


def rolling_vol(prices: Sequence[float], window: int = 5) -> list[float]:
    """Rolling annualized realized vol of log returns, aligned to price index."""
    rets = log_returns(list(prices))
    out: list[float] = []
    for i in range(len(rets)):
        seg = rets[max(0, i - window + 1) : i + 1]
        if len(seg) < 2:
            out.append(0.0)
            continue
        mean = sum(seg) / len(seg)
        var = sum((r - mean) ** 2 for r in seg) / (len(seg) - 1)
        out.append(math.sqrt(var * TRADING_DAYS))
    # align to price index: vol[i] describes the move ending at price i+1
    return [0.0] + out


def ks_2samp(a: Sequence[float], b: Sequence[float]) -> tuple[float, float]:
    """Two-sample Kolmogorov-Smirnov statistic and approximate p-value.

    Pure Python; the p-value uses the asymptotic Kolmogorov distribution,
    which is an approximation for small samples.
    """
    xs = sorted(float(v) for v in a)
    ys = sorted(float(v) for v in b)
    n, m = len(xs), len(ys)
    if n == 0 or m == 0:
        raise ValueError("ks_2samp requires non-empty samples")
    i = j = 0
    d = 0.0
    while i < n or j < m:
        x = xs[i] if i < n else math.inf
        y = ys[j] if j < m else math.inf
        if x <= y:
            i += 1
        if y <= x:
            j += 1
        d = max(d, abs(i / n - j / m))
    en = math.sqrt(n * m / (n + m))
    if d == 0.0:
        return 0.0, 1.0
    lam = (en + 0.12 + 0.11 / en) * d if en > 0 else 0.0
    # Kolmogorov survival function via alternating series.
    p = 0.0
    for k in range(1, 101):
        term = (-1) ** (k - 1) * math.exp(-2.0 * (k * lam) ** 2)
        p += term
        if abs(term) < 1e-12:
            break
    return d, max(0.0, min(1.0, 2.0 * p))


def observed_price_series(
    events: Sequence[WorldEvent],
) -> dict[str, list[tuple[str, float]]]:
    """Per-ticker (iso_time, close) from OBSERVED market.bar events, time-sorted."""
    rows: dict[str, list[tuple[str, float]]] = {}
    for event in events:
        if (event.event_type or "") != "market.bar":
            continue
        if event.kind not in {ProvenanceKind.OBSERVED, ProvenanceKind.DERIVED}:
            continue
        payload = event.payload or {}
        ticker = payload.get("ticker")
        close = payload.get("close")
        if not ticker or not isinstance(close, (int, float)):
            continue
        eff = event.temporal.effective_time
        rows.setdefault(str(ticker), []).append((iso(eff), eff, float(close)))
    out: dict[str, list[tuple[str, float]]] = {}
    for ticker, triplets in rows.items():
        triplets.sort(key=lambda t: t[1])
        out[ticker] = [(t_iso, c) for t_iso, _, c in triplets]
    return out


class MarketSymbolAlignment(BaseModel):
    symbol: str
    n_points: int = 0
    ks_statistic: float | None = None
    ks_pvalue: float | None = None
    return_mae: float | None = None
    vol_path_mae: float | None = None
    sim_drawdown: float | None = None
    obs_drawdown: float | None = None
    drawdown_error: float | None = None
    symbol_score: float = 0.0


class MarketAlignment(BaseModel):
    scenario_id: str
    scenario_class: str = "baseline"
    n_seeds: int = 0
    symbols: dict[str, MarketSymbolAlignment] = Field(default_factory=dict)
    skipped_symbols: list[str] = Field(default_factory=list)
    aggregate_score: float = 0.0
    notes: str = ""


def _mean(xs: Sequence[float]) -> float:
    xs = [float(v) for v in xs]
    return sum(xs) / len(xs) if xs else 0.0


def _mae(a: Sequence[float], b: Sequence[float]) -> float | None:
    n = min(len(a), len(b))
    if n == 0:
        return None
    return sum(abs(float(a[i]) - float(b[i])) for i in range(n)) / n


def _component_scores(
    ks_stat: float,
    vol_mae: float,
    obs_vol_mean: float,
    dd_error: float,
    obs_dd: float,
) -> float:
    ks_score = 1.0 - max(0.0, min(1.0, ks_stat))
    vol_score = 1.0 - min(1.0, vol_mae / max(obs_vol_mean, 0.02))
    dd_score = 1.0 - min(1.0, dd_error / max(abs(obs_dd), 0.02))
    return round((ks_score + vol_score + dd_score) / 3.0, 6)


def align_market(
    *,
    scenario_id: str,
    predicted: dict[str, Sequence[float]],
    observed: dict[str, Sequence[tuple[str, float]]],
    n_seeds: int = 0,
    vol_window: int = 5,
) -> MarketAlignment:
    """Align simulated per-symbol price series against observed t1 bars."""
    sclass = scenario_class_for(scenario_id)
    symbols: dict[str, MarketSymbolAlignment] = {}
    skipped: list[str] = []
    for sym, pred in predicted.items():
        obs_rows = observed.get(sym)
        if not obs_rows:
            skipped.append(sym)
            continue
        p = [float(v) for v in pred]
        o = [c for _, c in obs_rows]
        n = min(len(p), len(o))
        if n < 3:
            skipped.append(sym)
            continue
        p, o = p[:n], o[:n]
        p_rets, o_rets = log_returns(p), log_returns(o)
        ks_stat, ks_p = ks_2samp(p_rets, o_rets) if p_rets and o_rets else (1.0, 0.0)
        p_vol = rolling_vol(p, vol_window)[:n]
        o_vol = rolling_vol(o, vol_window)[:n]
        vol_mae = _mae(p_vol, o_vol) or 0.0
        sim_dd, obs_dd = max_drawdown(p), max_drawdown(o)
        dd_error = abs(sim_dd - obs_dd)
        score = _component_scores(ks_stat, vol_mae, _mean(o_vol), dd_error, obs_dd)
        symbols[sym] = MarketSymbolAlignment(
            symbol=sym,
            n_points=n,
            ks_statistic=round(ks_stat, 6),
            ks_pvalue=round(ks_p, 6),
            return_mae=round(_mae(p_rets, o_rets) or 0.0, 6),
            vol_path_mae=round(vol_mae, 6),
            sim_drawdown=round(sim_dd, 6),
            obs_drawdown=round(obs_dd, 6),
            drawdown_error=round(dd_error, 6),
            symbol_score=score,
        )
    for sym in observed:
        if sym not in predicted and sym not in skipped:
            skipped.append(sym)
    agg = round(_mean([s.symbol_score for s in symbols.values()]), 6) if symbols else 0.0
    notes = (
        f"{len(symbols)} aligned, {len(skipped)} skipped "
        f"({', '.join(sorted(skipped)) or 'none'}); "
        "scores measure calibration against one realized path, not predictive power."
    )
    return MarketAlignment(
        scenario_id=scenario_id,
        scenario_class=sclass,
        n_seeds=n_seeds,
        symbols=symbols,
        skipped_symbols=sorted(skipped),
        aggregate_score=agg,
        notes=notes,
    )


def record_market_alignment(
    ledger: RealityLedger,
    *,
    experiment_id: str,
    scenario_id: str,
    engine_name: str,
    seed: int | None,
    predicted: dict[str, Sequence[float]],
    observed: dict[str, Sequence[tuple[str, float]]],
    cutoff,
    source_versions: dict[str, str] | None = None,
    input_kinds: Sequence[str] | None = None,
    n_seeds: int = 0,
) -> tuple[MarketAlignment, list[str], list[dict]]:
    """Align, then append one ledger record per aligned symbol.

    Returns (alignment, ledger record ids, evaluation dicts).
    """
    alignment = align_market(
        scenario_id=scenario_id,
        predicted=predicted,
        observed=observed,
        n_seeds=n_seeds,
    )
    record_ids: list[str] = []
    evaluations: list[dict] = []
    for sym, sa in alignment.symbols.items():
        obs_prices = [c for _, c in observed[sym]]
        obs_times = [t for t, _ in observed[sym]]
        n = sa.n_points
        mean_px = _mean(obs_prices[:n]) or 1.0
        rec = ledger.record_prediction(
            experiment_id=experiment_id,
            scenario_id=scenario_id,
            model=engine_name,
            seed=seed,
            cutoff=cutoff,
            source_versions=source_versions,
            input_provenance_kinds=list(input_kinds or []),
            domain="market",
            scenario_class=alignment.scenario_class,
            predicted=[float(v) for v in list(predicted[sym])[:n]],
            observed=obs_prices[:n],
            times=obs_times[:n],
            metrics={
                "ks_statistic": sa.ks_statistic or 0.0,
                "ks_pvalue": sa.ks_pvalue or 0.0,
                "return_mae": sa.return_mae or 0.0,
                "vol_path_mae": sa.vol_path_mae or 0.0,
                "drawdown_error": sa.drawdown_error or 0.0,
                "symbol_score": sa.symbol_score,
            },
            # MAE verdict threshold: 2% of the mean observed price. A
            # fixed absolute threshold would be meaningless across tickers.
            threshold=0.02 * mean_px,
            notes=(
                f"market alignment class={alignment.scenario_class} "
                f"symbol_score={sa.symbol_score} aggregate={alignment.aggregate_score}"
            ),
        )
        record_ids.append(rec.id)
        evaluations.append(
            {
                "scenario_id": scenario_id,
                "scenario_class": alignment.scenario_class,
                "metric_name": f"market:{sym}",
                "ks_statistic": sa.ks_statistic,
                "ks_pvalue": sa.ks_pvalue,
                "return_mae": sa.return_mae,
                "vol_path_mae": sa.vol_path_mae,
                "drawdown_error": sa.drawdown_error,
                "symbol_score": sa.symbol_score,
                "n_seeds": n_seeds,
                "verdict": rec.verdict,
            }
        )
    return alignment, record_ids, evaluations
