"""eve-miro market-calibrate: MSM calibration of the marketsim archetypes.

Two modes, deliberately separated so the fitting path can never read
holdout data:

- ``fit`` (default): loads the frozen prereg and the fit targets file,
  runs Nelder-Mead plus threshold accepting from several starting points,
  writes the calibration result (parameters, objective, moments, errors,
  degeneracy report) to the output path. Never touches holdout data.
- ``validate``: takes a fit result plus the raw bars directory, computes
  the same moments on the HOLDOUT period once, and prints the
  fit-period vs holdout-period moment error table. Never feeds the
  optimizer; it only reports.

Everything calibrated is labeled as calibration output, not a forecast.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

from eve_miro.core.calibration import (
    CalibrationParams,
    OptimizeResult,
    degeneracy_report,
    load_fit_targets,
    make_objective,
    multistart,
    nelder_mead,
    simulate_daily_closes,
    threshold_accepting,
)
from eve_miro.core.calibration.moments import (
    AUTOCORR_LAGS,
    PCTS,
    TRADING_DAYS,
    abs_return_autocorr,
    hill_tail_index,
    log_returns,
    percentiles,
    rolling_std,
)
from eve_miro.paths import REPO_ROOT

DEFAULT_PREREG = REPO_ROOT / "experiments" / "market" / "calibration_prereg.json"
DEFAULT_OUT = REPO_ROOT / "storage" / "market" / "calibration_result.json"


def fail(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 1


def load_prereg(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"prereg file not found: {path}")
    prereg = json.loads(path.read_text(encoding="utf-8"))
    if not prereg.get("frozen"):
        raise ValueError(f"prereg {path} is not marked frozen; refusing to fit")
    return prereg



def cmd_fit_single(objective, x0, idx, prereg, fit_targets,
                   prereg_path, targets_path, out_path) -> int:
    """Run one starting point (Nelder-Mead plus threshold accepting) and
    checkpoint the result immediately, so a long multi-start search survives
    interruptions."""
    print(f"start {idx}: Nelder-Mead...")
    local = nelder_mead(objective.__call__, x0, prereg)
    print(f"start {idx}: Nelder-Mead done J={local.value:.4f} ({local.n_evaluations} evals)")
    print(f"start {idx}: threshold accepting...")
    final = threshold_accepting(objective.__call__, local, prereg, seed=1000 + idx)
    print(f"start {idx}: done J={final.value:.4f} ({final.n_evaluations} evals total)")
    final.detail["start_index"] = idx
    ev = objective.evaluate(final.params)
    checkpoint = {
        "start_index": idx,
        "params": final.params.to_dict(),
        "objective": final.value,
        "n_evaluations": final.n_evaluations,
        "converged": final.converged,
        "moments": ev["moments"],
        "percentile_grids": ev["percentile_grids"],
        "errors": ev["errors"],
        "prereg": str(prereg_path),
        "targets": str(targets_path),
        "fit_ticker": objective.ticker,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")
    print(f"start {idx} checkpoint written to {out_path}")
    return 0


def cmd_combine(args: argparse.Namespace) -> int:
    """Merge per-start checkpoints into the final calibration result with
    the degeneracy report."""
    inputs = [Path(s) for s in args.inputs]
    checkpoints = []
    for p in inputs:
        if not p.is_file():
            return fail(f"checkpoint not found: {p}")
        checkpoints.append(json.loads(p.read_text(encoding="utf-8")))
    if not checkpoints:
        return fail("no checkpoints given")
    results = []
    for cp in checkpoints:
        r = OptimizeResult(
            params=CalibrationParams.from_dict(cp["params"]),
            value=float(cp["objective"]),
            n_evaluations=int(cp["n_evaluations"]),
            converged=bool(cp["converged"]),
            detail={"start_index": cp["start_index"]},
        )
        results.append(r)
    report = degeneracy_report(results)
    best = results[report["best_index"]]
    best_cp = checkpoints[report["best_index"]]
    prereg_path = best_cp["prereg"]
    prereg = json.loads(Path(prereg_path).read_text(encoding="utf-8")) if Path(prereg_path).is_file() else {}
    fit_targets = load_fit_targets(best_cp["targets"])
    result = {
        "prereg": prereg_path,
        "targets": best_cp["targets"],
        "fit_ticker": best_cp["fit_ticker"],
        "disclaimer": (
            "CALIBRATION OUTPUT. Agent parameters fitted by simulated method "
            "of moments against historical statistics. Not a forecast of "
            "market prices. See docs/market-calibration.md for limits."
        ),
        "best": {
            "params": best.params.to_dict(),
            "objective": best.value,
            "n_evaluations": best.n_evaluations,
            "converged": best.converged,
            "moments": best_cp["moments"],
            "percentile_grids": best_cp["percentile_grids"],
            "errors": best_cp["errors"],
        },
        "starts": [
            {
                "start_index": cp["start_index"],
                "params": cp["params"],
                "objective": cp["objective"],
                "n_evaluations": cp["n_evaluations"],
                "converged": cp["converged"],
            }
            for cp in checkpoints
        ],
        "degeneracy": report,
    }
    # fit target moments for the validate mode
    fit_target_moments: dict[str, Any] = {}
    for spec in prereg.get("moments", []):
        key = spec["key"]
        if key.endswith(".percentile_mae"):
            base = key[: -len(".percentile_mae")]
            node: Any = fit_targets["tickers"][best_cp["fit_ticker"]]
            for part in base.split("."):
                node = node[part]
            fit_target_moments[key] = {f"p{p}": float(node[f"p{p}"]) for p in (5, 25, 50, 75, 95)}
        else:
            node = fit_targets["tickers"][best_cp["fit_ticker"]]
            for part in key.split("."):
                node = node[part]
            fit_target_moments[key] = float(node)
    result["fit_target_moments"] = fit_target_moments
    result["moment_specs"] = prereg.get("moments", [])
    # drawdown diagnostic on the best parameters with a fresh seed
    dd_closes = simulate_daily_closes(best.params, days=252, steps_per_day=24, warmup_days=2, seed=999)
    dd_prices = np.array(dd_closes)
    peak = np.maximum.accumulate(dd_prices)
    sim_dd = float(np.min(dd_prices / peak - 1.0))
    target_dd = fit_targets["tickers"][best_cp["fit_ticker"]]["max_drawdown_252d"]
    result["drawdown_diagnostic"] = {
        "simulated_252d_max_drawdown": sim_dd,
        "target_252d_mean": float(target_dd["mean"]),
        "target_252d_p5": float(target_dd["p5"]),
        "target_252d_p95": float(target_dd["p95"]),
        "note": "Diagnostic only: drawdown was not in the optimized moment set.",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nbest objective J={best.value:.4f}")
    print("calibrated parameters:")
    for name, val in best.params.to_dict().items():
        print(f"  {name:22s} {val:.6g}")
    print(f"\ndegeneracy: {report['note']}")
    print(f"combined result written to {out}")
    return 0


def cmd_fit(args: argparse.Namespace) -> int:
    prereg_path = Path(args.prereg)
    targets_path = Path(args.targets)
    try:
        prereg = load_prereg(prereg_path)
        fit_targets = load_fit_targets(targets_path)
    except (FileNotFoundError, ValueError) as exc:
        return fail(str(exc))

    objective = make_objective(prereg, fit_targets)
    dim = len(CalibrationParams.starting_point().to_unit())
    starts = [np.array(CalibrationParams.starting_point().to_unit())]
    # Degeneracy starts: low and high corners of unit space.
    starts.append(np.full(dim, -1.5))
    starts.append(np.full(dim, 1.5))
    n_starts = max(1, min(args.starts, 3))
    starts = starts[:n_starts]

    print(f"fitting {dim} parameters from {n_starts} starting point(s)...")
    print(f"prereg: {prereg_path} (frozen)")
    print(f"targets: {targets_path} (fit period {fit_targets.get('fit_period', '?')})")
    if args.start_index is not None:
        idx = args.start_index
        if idx < 0 or idx >= len(starts):
            return fail(f"--start-index must be 0..{len(starts)-1}")
        return cmd_fit_single(objective, starts[idx], idx, prereg, fit_targets,
                              prereg_path, targets_path, Path(args.out))
    results = multistart(objective.__call__, starts, prereg)
    report = degeneracy_report(results)
    best = results[report["best_index"]]
    best_eval = objective.evaluate(best.params)

    # Drawdown diagnostic (not an optimized moment): simulated window max
    # drawdown vs the target 252-day distribution, reported for context.
    result = {
        "prereg": str(prereg_path),
        "targets": str(targets_path),
        "fit_ticker": objective.ticker,
        "disclaimer": (
            "CALIBRATION OUTPUT. Agent parameters fitted by simulated method "
            "of moments against historical statistics. Not a forecast of "
            "market prices. See docs/market-calibration.md for limits."
        ),
        "best": {
            "params": best.params.to_dict(),
            "objective": best.value,
            "n_evaluations": best.n_evaluations,
            "converged": best.converged,
            "moments": best_eval["moments"],
            "percentile_grids": best_eval["percentile_grids"],
            "errors": best_eval["errors"],
        },
        "starts": [
            {
                "start_index": r.detail.get("start_index", i),
                "params": r.params.to_dict(),
                "objective": r.value,
                "n_evaluations": r.n_evaluations,
                "converged": r.converged,
            }
            for i, r in enumerate(results)
        ],
        "degeneracy": report,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Store the fit target moments alongside the result so the validate mode
    # can compute holdout errors on identical scales without re-reading
    # anything beyond fit-period data.
    fit_target_moments: dict[str, float] = {}
    for spec in prereg["moments"]:
        key = spec["key"]
        if key.endswith(".percentile_mae"):
            base = key[: -len(".percentile_mae")]
            node: Any = fit_targets["tickers"][objective.ticker]
            for part in base.split("."):
                node = node[part]
            fit_target_moments[key] = {f"p{p}": float(node[f"p{p}"]) for p in (5, 25, 50, 75, 95)}
        else:
            node = fit_targets["tickers"][objective.ticker]
            for part in key.split("."):
                node = node[part]
            fit_target_moments[key] = float(node)
    result["fit_target_moments"] = fit_target_moments
    result["moment_specs"] = prereg["moments"]
    # Drawdown diagnostic (not an optimized moment): one 252-day run with the
    # best parameters and a fresh seed, compared against the target 252-day
    # drawdown distribution for context.
    dd_closes = simulate_daily_closes(
        best.params, days=252, steps_per_day=24, warmup_days=2, seed=999
    )
    dd_prices = np.array(dd_closes)
    peak = np.maximum.accumulate(dd_prices)
    sim_dd = float(np.min(dd_prices / peak - 1.0))
    target_dd = fit_targets["tickers"][objective.ticker]["max_drawdown_252d"]
    result["drawdown_diagnostic"] = {
        "simulated_252d_max_drawdown": sim_dd,
        "target_252d_mean": float(target_dd["mean"]),
        "target_252d_p5": float(target_dd["p5"]),
        "target_252d_p95": float(target_dd["p95"]),
        "note": "Diagnostic only: drawdown was not in the optimized moment set.",
    }
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"\nbest objective J={best.value:.4f} ({best.n_evaluations} evaluations)")
    print("calibrated parameters:")
    for name, val in best.params.to_dict().items():
        print(f"  {name:22s} {val:.6g}")
    print(f"\ndegeneracy: {report['note']}")
    print(f"result written to {out}")
    return 0


def holdout_moments(raw_dir: Path, ticker: str, fit_end: str = "2023-12-31") -> dict[str, float]:
    """Compute the MSM moment vector on the holdout period, once, for reporting.

    This function is only called by the validate mode. It never feeds the
    optimizer.
    """
    import csv

    closes: list[tuple[str, float]] = []
    with open(raw_dir / f"{ticker}_daily.csv", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            closes.append((row["Date"][:10], float(row["Adj Close"])))
    closes.sort()
    holdout = np.array([c for d, c in closes if d > fit_end], dtype=float)
    if len(holdout) < 60:
        raise ValueError(f"holdout period too short for {ticker}: {len(holdout)} bars")
    rets = log_returns(holdout)
    out: dict[str, float] = {}
    out["log_return.mean"] = float(np.mean(rets))
    out["log_return.std"] = float(np.std(rets, ddof=1))
    from scipy import stats as scipy_stats

    out["log_return.skew"] = float(scipy_stats.skew(rets, bias=False))
    out["log_return.excess_kurtosis"] = float(scipy_stats.kurtosis(rets, bias=False))
    for lag in AUTOCORR_LAGS:
        out[f"abs_return_autocorr.lag{lag}"] = abs_return_autocorr(rets, lag)
    for window, tag in ((5, "rv5"), (20, "rv20")):
        rv = rolling_std(rets, window)
        rv = rv[~np.isnan(rv)] * np.sqrt(TRADING_DAYS)
        out[f"realized_vol_annualized.{tag}.mean"] = float(np.mean(rv))
        out[f"realized_vol_annualized.{tag}.std"] = float(np.std(rv, ddof=1))
        out[f"realized_vol_annualized.{tag}.percentiles"] = percentiles(rv)
    out["hill_tail_index.left_5pct"] = hill_tail_index(rets, "left")
    out["hill_tail_index.right_5pct"] = hill_tail_index(rets, "right")
    out["n_bars"] = float(len(holdout))
    return out


def cmd_validate(args: argparse.Namespace) -> int:
    result_path = Path(args.result)
    raw_dir = Path(args.raw_dir)
    if not result_path.is_file():
        return fail(f"calibration result not found: {result_path}")
    if not raw_dir.is_dir():
        return fail(f"raw bars directory not found: {raw_dir}")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    ticker = result.get("fit_ticker", "SPY")
    try:
        hold = holdout_moments(raw_dir, ticker)
    except (FileNotFoundError, ValueError) as exc:
        return fail(str(exc))
    # Fit target moments and prereg scales are stored in the result file
    # (fit-period data only). Validate mode never optimizes.
    fit_moments = result["best"]["moments"]
    fit_errors = result["best"]["errors"]
    fit_target_moments: dict[str, Any] = result.get("fit_target_moments", {})
    moment_specs: list[dict[str, Any]] = result.get("moment_specs", [])
    if not fit_target_moments or not moment_specs:
        return fail("result file lacks fit_target_moments/moment_specs; refit with current CLI")

    def scale_for(spec: dict[str, Any], key: str) -> float:
        s = spec["scale"]
        if key.endswith(".percentile_mae"):
            grid = fit_target_moments[key]
            vals = [grid[f"p{p}"] for p in PCTS]
            if s == "abs_target_mean":
                return max(float(np.mean(vals)), 1e-6)
        else:
            t = float(fit_target_moments[key])
            if s == "abs_target":
                return max(abs(t), 1e-6)
            if s == "max(abs_target, 1.0)":
                return max(abs(t), 1.0)
            if s == "max(abs_target, 0.05)":
                return max(abs(t), 0.05)
        try:
            return float(s)
        except (TypeError, ValueError):
            return 1.0

    spec_by_key = {s["key"]: s for s in moment_specs}
    print(f"holdout validation for {ticker}: {int(hold['n_bars'])} bars after 2023-12-31")
    print("The fitted model never saw the holdout period. Both columns use the")
    print("frozen prereg scales; holdout errors are (simulated - holdout) / scale.")
    print(f"\n{'moment':45s} {'fit err':>10s} {'holdout err':>12s}")
    for key in fit_errors:
        spec = spec_by_key.get(key, {"scale": "1.0"})
        scale = scale_for(spec, key)
        if key.endswith(".percentile_mae"):
            base = key[: -len(".percentile_mae")]
            sim_p = result["best"].get("percentile_grids", {}).get(base + ".percentiles", {})
            hold_p = hold.get(base + ".percentiles", {})
            mae = float(np.mean([abs(sim_p[f"p{p}"] - hold_p[f"p{p}"]) for p in PCTS]))
            herr = mae / scale
        else:
            herr = (fit_moments[key] - hold[key]) / scale
        print(f"  {key:43s} {fit_errors[key]:+10.3f} {herr:+12.3f}")
    return 0


def cmd_market_calibrate(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eve-miro market-calibrate")
    sub = parser.add_subparsers(dest="mode", required=True)

    p_fit = sub.add_parser("fit", help="fit agent parameters by MSM (fit targets only)")
    p_fit.add_argument("--prereg", default=str(DEFAULT_PREREG))
    p_fit.add_argument("--targets", required=True, help="fit targets JSON (fit period only)")
    p_fit.add_argument("--out", default=str(DEFAULT_OUT))
    p_fit.add_argument("--starts", type=int, default=3, help="starting points 1..3")
    p_fit.add_argument("--start-index", type=int, default=None,
                       help="run only one start (0, 1, or 2) and write a checkpoint file")

    p_val = sub.add_parser("validate", help="report holdout moment table (never optimizes)")
    p_val.add_argument("--result", required=True, help="calibration result JSON from fit")
    p_val.add_argument("--raw-dir", required=True, help="directory with <TICKER>_daily.csv raw bars")

    p_combine = sub.add_parser("combine", help="merge per-start checkpoints into the final result")
    p_combine.add_argument("--inputs", nargs="+", required=True, help="per-start checkpoint JSON files")
    p_combine.add_argument("--out", required=True, help="combined calibration result JSON")

    args = parser.parse_args(argv if argv is not None else [])
    if args.mode == "fit":
        return cmd_fit(args)
    if args.mode == "validate":
        return cmd_validate(args)
    if args.mode == "combine":
        return cmd_combine(args)
    return fail(f"unknown mode {args.mode}")
