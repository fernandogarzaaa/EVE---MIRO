"""MSM objective: weighted distance between simulated and target moments.

The moment list, scales, and weights come from the frozen prereg file.
``make_objective`` returns a deterministic callable over the unit
hypercube (common random numbers: fixed replication seeds), suitable for
scipy Nelder-Mead. ``evaluate`` runs one parameter vector and returns the
full breakdown for reporting.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from eve_miro.core.calibration.moments import compute_moments
from eve_miro.core.calibration.params import CalibrationParams
from eve_miro.core.calibration.runner import simulate_daily_closes

MOMENT_KEYS: tuple[str, ...] = (
    "log_return.std",
    "log_return.excess_kurtosis",
    "log_return.skew",
    "abs_return_autocorr.lag1",
    "abs_return_autocorr.lag5",
    "abs_return_autocorr.lag10",
    "abs_return_autocorr.lag20",
    "realized_vol_annualized.rv5.mean",
    "realized_vol_annualized.rv5.std",
    "realized_vol_annualized.rv20.mean",
    "realized_vol_annualized.rv20.std",
    "realized_vol_annualized.rv5.percentile_mae",
    "realized_vol_annualized.rv20.percentile_mae",
    "hill_tail_index.left_5pct",
    "hill_tail_index.right_5pct",
    "log_return.mean",
)


def _get_target(targets: dict[str, Any], ticker: str, key: str) -> Any:
    node: Any = targets["tickers"][ticker]
    for part in key.split("."):
        node = node[part]
    return node


def _resolve_scale(scale_spec: str, target: Any, ticker_targets: dict[str, Any]) -> float:
    if scale_spec == "abs_target":
        return max(abs(float(target)), 1e-6)
    if scale_spec == "max(abs_target, 1.0)":
        return max(abs(float(target)), 1.0)
    if scale_spec == "max(abs_target, 0.05)":
        return max(abs(float(target)), 0.05)
    if scale_spec == "abs_target_mean":
        pcts = target
        return max(float(np.mean([pcts[f"p{p}"] for p in (5, 25, 50, 75, 95)])), 1e-6)
    try:
        return float(scale_spec)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unknown scale spec {scale_spec!r}") from exc


def standardized_errors(
    sim_moments: dict[str, float],
    fit_targets: dict[str, Any],
    ticker: str,
    moment_specs: list[dict[str, Any]],
) -> dict[str, float]:
    """Per-moment standardized errors e_i = (sim - target) / scale.

    For percentile_mae moments the simulated value is itself a mean
    absolute error against the target percentile grid, so the target
    moment value is 0.
    """
    ticker_targets = fit_targets["tickers"][ticker]
    errors: dict[str, float] = {}
    for spec in moment_specs:
        key = spec["key"]
        weight = float(spec.get("weight", 1.0))
        if weight == 0:
            continue
        if key.endswith(".percentile_mae"):
            base = key[: -len(".percentile_mae")]
            target_pcts = _get_target(fit_targets, ticker, base)
            sim_pcts = sim_moments[base + ".percentiles"]
            mae = float(np.mean([abs(sim_pcts[f"p{p}"] - target_pcts[f"p{p}"]) for p in (5, 25, 50, 75, 95)]))
            scale = _resolve_scale(spec["scale"], target_pcts, ticker_targets)
            errors[key] = mae / scale
        else:
            target = float(_get_target(fit_targets, ticker, key))
            sim = float(sim_moments[key])
            if not math.isfinite(sim):
                # Degenerate simulation (e.g., a dead market with no price
                # movement). Penalize heavily so the optimizer walks away,
                # rather than crashing the whole search.
                print(f"warning: non-finite simulated moment {key}; penalizing")
                errors[key] = 10.0
                continue
            scale = _resolve_scale(spec["scale"], target, ticker_targets)
            errors[key] = (sim - target) / scale
    return errors


def weighted_sse(errors: dict[str, float], moment_specs: list[dict[str, Any]]) -> float:
    total = 0.0
    weights = {s["key"]: float(s.get("weight", 1.0)) for s in moment_specs}
    for key, e in errors.items():
        if not math.isfinite(e):
            raise ValueError(f"non-finite standardized error for {key}: {e}")
        total += weights[key] * e * e
    return total


class Objective:
    """Deterministic MSM objective over the unit hypercube."""

    def __init__(
        self,
        prereg: dict[str, Any],
        fit_targets: dict[str, Any],
        *,
        ticker: str | None = None,
    ) -> None:
        self.prereg = prereg
        self.fit_targets = fit_targets
        self.moment_specs: list[dict[str, Any]] = prereg["moments"]
        sim_cfg = prereg["simulation"]
        self.days: int = int(sim_cfg["days"])
        self.steps_per_day: int = int(sim_cfg["steps_per_day"])
        self.warmup_days: int = int(sim_cfg["warmup_days"])
        self.replication_seeds: list[int] = [int(s) for s in sim_cfg["replication_seeds"]]
        self.ticker = ticker or prereg["targets"]["fit_ticker"]
        if self.ticker not in fit_targets["tickers"]:
            raise ValueError(
                f"fit ticker {self.ticker!r} not in targets (have {sorted(fit_targets['tickers'])})"
            )
        self.n_evaluations = 0

    def simulate_moments(self, params: CalibrationParams) -> dict[str, float]:
        reps = [
            np.asarray(
                simulate_daily_closes(
                    params,
                    days=self.days,
                    steps_per_day=self.steps_per_day,
                    warmup_days=self.warmup_days,
                    seed=seed,
                )
            )
            for seed in self.replication_seeds
        ]
        return compute_moments(reps)

    def evaluate(self, params: CalibrationParams) -> dict[str, Any]:
        sim_moments = self.simulate_moments(params)
        errors = standardized_errors(sim_moments, self.fit_targets, self.ticker, self.moment_specs)
        value = weighted_sse(errors, self.moment_specs)
        return {
            "value": value,
            "params": params.to_dict(),
            "moments": {k: v for k, v in sim_moments.items() if not k.endswith(".percentiles")},
            "percentile_grids": {k: v for k, v in sim_moments.items() if k.endswith(".percentiles")},
            "errors": errors,
        }

    def __call__(self, u: np.ndarray) -> float:
        self.n_evaluations += 1
        params = CalibrationParams.from_unit(u)
        return self.evaluate(params)["value"]


def make_objective(
    prereg: dict[str, Any],
    fit_targets: dict[str, Any],
    *,
    ticker: str | None = None,
) -> Objective:
    return Objective(prereg, fit_targets, ticker=ticker)
