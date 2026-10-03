"""AAPL diagnostic: evaluate the SPY-calibrated parameters against AAPL
fit-period targets. The prereg declares AAPL as a diagnostic check for
overfitting to SPY idiosyncrasies, not as an optimization target.
"""
import json
import sys

from eve_miro.core.calibration import CalibrationParams, load_fit_targets, make_objective


def main() -> int:
    result_path = sys.argv[1]
    targets_path = sys.argv[2]
    result = json.loads(open(result_path, encoding="utf-8").read())
    prereg = json.loads(open(result["prereg"], encoding="utf-8").read())
    targets = load_fit_targets(targets_path)
    params = CalibrationParams.from_dict(result["best"]["params"])
    obj = make_objective(prereg, targets, ticker="AAPL")
    ev = obj.evaluate(params)
    print("AAPL diagnostic (SPY-calibrated params on AAPL fit targets)")
    print(f"objective J={ev['value']:.4f}  (SPY fit J={result['best']['objective']:.4f})")
    print(f"{'moment':45s} {'err':>7s}")
    for spec in prereg["moments"]:
        key = spec["key"]
        err = ev["errors"][key]
        if isinstance(err, dict):
            mag = max(abs(v) for v in err.values())
            shown = f"max|e|={mag:.3f}"
        else:
            shown = f"{err:+.3f}"
        print(f"  {key:43s} {shown:>7s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
