"""Moment computation for MSM calibration.

Mirrors the definitions in the calibration research ``compute_targets.py``
(pandas semantics) using numpy/scipy so the simulated moments are directly
comparable to ``targets_fit.json``:

- log returns on daily closes; std with ddof=1
- skew / excess kurtosis: bias-corrected Fisher-Pearson (pandas .skew()/.kurt())
- realized vol: rolling ddof=1 std of log returns, annualized by sqrt(252)
- abs-return autocorrelation: Pearson on overlapping segments (pandas .autocorr)
- percentiles: linear interpolation (pandas .quantile default)
- Hill tail index: same order-statistic estimator
"""

from __future__ import annotations

import numpy as np
from scipy import stats as scipy_stats

TRADING_DAYS = 252
TAIL_FRAC = 0.05
PCTS = (5, 25, 50, 75, 95)
AUTOCORR_LAGS = (1, 5, 10, 20)


def log_returns(prices: np.ndarray) -> np.ndarray:
    p = np.asarray(prices, dtype=float)
    if np.any(p <= 0):
        raise ValueError("prices must be positive for log returns")
    return np.diff(np.log(p))


def rolling_std(x: np.ndarray, window: int) -> np.ndarray:
    """Rolling ddof=1 std, min_periods=window; leading entries are NaN."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    out = np.full(n, np.nan)
    if n < window or window < 2:
        return out
    cumsum = np.concatenate([[0.0], np.cumsum(x)])
    cumsum2 = np.concatenate([[0.0], np.cumsum(x * x)])
    for i in range(window - 1, n):
        seg_sum = cumsum[i + 1] - cumsum[i + 1 - window]
        seg_sum2 = cumsum2[i + 1] - cumsum2[i + 1 - window]
        var = (seg_sum2 - seg_sum * seg_sum / window) / (window - 1)
        out[i] = float(np.sqrt(max(var, 0.0)))
    return out


def abs_return_autocorr(returns: np.ndarray, lag: int) -> float:
    a = np.abs(np.asarray(returns, dtype=float))
    if lag <= 0 or lag >= len(a):
        raise ValueError(f"lag={lag} invalid for {len(a)} returns")
    x, y = a[lag:], a[:-lag]
    if np.std(x) == 0.0 or np.std(y) == 0.0:
        return 0.0
    return float(np.corrcoef(x, y)[0, 1])


def hill_tail_index(x: np.ndarray, tail: str, frac: float = TAIL_FRAC) -> float:
    vals = np.asarray(x, dtype=float) if tail == "right" else -np.asarray(x, dtype=float)
    vals = np.sort(vals)[::-1]
    k = max(2, int(np.floor(frac * len(vals))))
    tail_vals = vals[:k]
    if tail_vals[-1] <= 0:
        return float("nan")
    h = float(np.mean(np.log(tail_vals / tail_vals[-1])))
    return 1.0 / h if h > 0 else float("nan")


def percentiles(x: np.ndarray) -> dict[str, float]:
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) == 0:
        raise ValueError("percentiles of empty series")
    qs = np.percentile(x, list(PCTS))
    return {f"p{p}": float(v) for p, v in zip(PCTS, qs)}


def compute_moments(daily_closes_per_rep: list[np.ndarray]) -> dict[str, float]:
    """Compute the 16 MSM moments from simulated daily closes.

    Distributional moments pool log returns across replications;
    consecutive-series moments (autocorrelations) are computed per
    replication and averaged. Keys match the prereg moment list.
    """
    reps = [np.asarray(c, dtype=float) for c in daily_closes_per_rep]
    if not reps or any(len(r) < 30 for r in reps):
        raise ValueError("each replication needs at least 30 daily closes")
    rets_per_rep = [log_returns(r) for r in reps]
    pooled = np.concatenate(rets_per_rep)

    out: dict[str, float] = {}
    out["log_return.mean"] = float(np.mean(pooled))
    out["log_return.std"] = float(np.std(pooled, ddof=1))
    out["log_return.skew"] = float(scipy_stats.skew(pooled, bias=False))
    out["log_return.excess_kurtosis"] = float(scipy_stats.kurtosis(pooled, bias=False))
    for lag in AUTOCORR_LAGS:
        vals = [abs_return_autocorr(r, lag) for r in rets_per_rep]
        out[f"abs_return_autocorr.lag{lag}"] = float(np.mean(vals))
    for window, tag in ((5, "rv5"), (20, "rv20")):
        rv_all = []
        for r in rets_per_rep:
            rv = rolling_std(r, window)
            rv_all.append(rv[~np.isnan(rv)])
        rv_pooled = np.concatenate(rv_all)
        out[f"realized_vol_annualized.{tag}.mean"] = float(np.mean(rv_pooled) * np.sqrt(TRADING_DAYS))
        out[f"realized_vol_annualized.{tag}.std"] = float(np.std(rv_pooled, ddof=1) * np.sqrt(TRADING_DAYS))
        out[f"realized_vol_annualized.{tag}.percentiles"] = percentiles(rv_pooled * np.sqrt(TRADING_DAYS))
    out["hill_tail_index.left_5pct"] = hill_tail_index(pooled, "left")
    out["hill_tail_index.right_5pct"] = hill_tail_index(pooled, "right")
    return out
