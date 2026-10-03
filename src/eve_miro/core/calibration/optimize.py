"""MSM optimizer driver: Nelder-Mead plus threshold accepting.

Follows the Dicks and Gebbie recipe from the architecture survey:
local Nelder-Mead search, then stochastic threshold-accepting rounds that
perturb the incumbent and re-optimize, accepting moves within a shrinking
threshold. Multi-start wrappers support the prereg degeneracy analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
from scipy.optimize import minimize

from eve_miro.core.calibration.params import PARAM_SPECS, CalibrationParams


@dataclass
class OptimizeResult:
    params: CalibrationParams
    value: float
    n_evaluations: int
    converged: bool
    detail: dict[str, Any] = field(default_factory=dict)


def _check_prereg_optimizer(prereg: dict[str, Any]) -> dict[str, Any]:
    cfg = prereg.get("optimizer")
    if not isinstance(cfg, dict):
        raise ValueError("prereg missing optimizer config")
    for key in ("xatol", "fatol", "max_evaluations"):
        if key not in cfg:
            raise ValueError(f"prereg optimizer config missing {key!r}")
    return cfg


def nelder_mead(
    objective: Callable[[np.ndarray], float],
    x0: np.ndarray,
    prereg: dict[str, Any],
    *,
    max_evaluations: int | None = None,
) -> OptimizeResult:
    """Unconstrained Nelder-Mead in unit-hypercube space."""
    cfg = _check_prereg_optimizer(prereg)
    maxfev = int(max_evaluations or cfg["max_evaluations"])
    if maxfev <= 0:
        raise ValueError(f"max_evaluations must be positive, got {maxfev}")
    x0 = np.asarray(x0, dtype=float)
    if x0.shape != (len(PARAM_SPECS),):
        raise ValueError(f"x0 must have {len(PARAM_SPECS)} entries, got {x0.shape}")
    res = minimize(
        objective,
        x0,
        method="Nelder-Mead",
        options={
            "maxfev": maxfev,
            "xatol": float(cfg["xatol"]),
            "fatol": float(cfg["fatol"]),
        },
    )
    return OptimizeResult(
        params=CalibrationParams.from_unit(res.x),
        value=float(res.fun),
        n_evaluations=int(res.nfev),
        converged=bool(res.success),
        detail={"nit": int(res.nit), "message": str(res.message)},
    )


def threshold_accepting(
    objective: Callable[[np.ndarray], float],
    incumbent: OptimizeResult,
    prereg: dict[str, Any],
    *,
    rounds: int = 3,
    tries_per_round: int = 3,
    step_std: float = 0.35,
    seed: int = 7,
    inner_max_evaluations: int = 100,
) -> OptimizeResult:
    """Stochastic global moves around the incumbent.

    Each round perturbs the incumbent in unit space, re-runs Nelder-Mead,
    and accepts the result if it is within the round's threshold of the
    best value seen. Thresholds shrink geometrically.
    """
    _check_prereg_optimizer(prereg)  # validates config; thresholds are derived below
    rounds = int(rounds)
    if rounds <= 0:
        raise ValueError("rounds must be positive")
    rng = np.random.default_rng(seed)
    dim = len(PARAM_SPECS)
    best = incumbent
    total_evals = best.n_evaluations
    base = max(abs(best.value), 1e-6)
    for r in range(rounds):
        threshold = base * (0.25 ** (r + 1))
        for _ in range(tries_per_round):
            x_try = np.array(best.params.to_unit()) + rng.normal(0.0, step_std, dim)
            cand = nelder_mead(objective, x_try, prereg, max_evaluations=inner_max_evaluations)
            total_evals += cand.n_evaluations
            if cand.value < best.value + threshold:
                best = cand
                base = max(abs(best.value), 1e-6)
    best.n_evaluations = total_evals
    best.detail["threshold_accepting_rounds"] = rounds
    return best


def multistart(
    objective: Callable[[np.ndarray], float],
    starts: list[np.ndarray],
    prereg: dict[str, Any],
) -> list[OptimizeResult]:
    """Run the full search from each starting point for degeneracy analysis."""
    if not starts:
        raise ValueError("multistart needs at least one starting point")
    results = []
    for i, x0 in enumerate(starts):
        local = nelder_mead(objective, np.asarray(x0, dtype=float), prereg)
        final = threshold_accepting(objective, local, prereg, seed=1000 + i)
        final.detail["start_index"] = i
        results.append(final)
    return results


def degeneracy_report(results: list[OptimizeResult]) -> dict[str, Any]:
    """Honest identifiability check across multi-start results.

    If final objectives agree within 10 percent but parameter vectors
    differ substantially, the parameters are degenerate: report it, do not
    present a spuriously precise point estimate.
    """
    if not results:
        raise ValueError("no results to analyze")
    values = np.array([r.value for r in results])
    best_idx = int(np.argmin(values))
    best_val = float(values[best_idx])
    param_matrix = np.array([r.params.to_unit() for r in results])
    spread = float(np.max(np.std(param_matrix, axis=0))) if len(results) > 1 else 0.0
    rel_range = float((values.max() - values.min()) / max(abs(best_val), 1e-9))
    # Pairwise check: any two starts whose objectives agree within 10% but
    # whose parameter vectors differ substantially are a degenerate pair,
    # even when a third start found a better basin.
    degenerate_pairs: list[dict[str, Any]] = []
    for i in range(len(results)):
        for j in range(i + 1, len(results)):
            denom = max(abs(values[i]), abs(values[j]), 1e-9)
            if abs(values[i] - values[j]) / denom < 0.10:
                dist = float(np.linalg.norm(param_matrix[i] - param_matrix[j]))
                if dist > 1.0:
                    degenerate_pairs.append(
                        {"starts": [i, j], "values": [float(values[i]), float(values[j])],
                         "unit_distance": dist}
                    )
    degenerate = bool(degenerate_pairs) or (rel_range < 0.10 and spread > 0.5)
    per_param_range: dict[str, float] = {}
    for j, spec in enumerate(PARAM_SPECS):
        col = param_matrix[:, j]
        per_param_range[spec.name] = float(col.max() - col.min())
    note: str
    if degenerate_pairs:
        p = degenerate_pairs[0]
        note = (
            f"DEGENERATE: starts {p['starts'][0]} and {p['starts'][1]} reach "
            f"J={p['values'][0]:.4f} and J={p['values'][1]:.4f} (within 10%) "
            f"but sit {p['unit_distance']:.2f} apart in unit parameter space. "
            "Do not treat the point estimate as identified."
        )
    elif rel_range < 0.10 and spread > 0.5:
        note = (
            "DEGENERATE: objectives agree within 10% but parameters differ; "
            "do not treat the point estimate as identified."
        )
    else:
        note = "No degeneracy detected at the 10% objective-agreement threshold."
    return {
        "n_starts": len(results),
        "best_index": best_idx,
        "best_value": best_val,
        "objective_rel_range": rel_range,
        "param_unit_spread": spread,
        "per_param_unit_range": per_param_range,
        "degenerate": bool(degenerate),
        "degenerate_pairs": degenerate_pairs,
        "note": note,
    }
