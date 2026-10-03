"""Fit-target loading with a structural holdout guard.

The fitter accepts only the fit targets file. This loader strips holdout
metadata (``holdout_range``, ``n_bars_holdout``) and refuses any payload
that carries holdout-derived statistics, so a fitting run cannot see the
holdout period even by accident. Holdout validation lives in a separate
code path (the CLI ``validate`` mode) that never feeds the optimizer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HOLDOUT_METADATA_KEYS = ("holdout_range", "n_bars_holdout")


def load_fit_targets(path: str | Path) -> dict[str, Any]:
    """Load per-ticker fit-period moments, structurally excluding holdout data."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"fit targets file not found: {p}")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"fit targets file is not valid JSON: {p}: {exc}") from exc
    if not isinstance(raw, dict) or not raw:
        raise ValueError(f"fit targets file must be a non-empty object: {p}")
    tickers: dict[str, dict[str, Any]] = {}
    fit_period = ""
    for ticker, entry in raw.items():
        if ticker == "meta":
            # Provenance block, not a ticker. Keep the fit-period label only;
            # the holdout date range is metadata, never statistics.
            if isinstance(entry, dict):
                fit_period = str(entry.get("fit_period", ""))
            continue
        if not isinstance(entry, dict):
            raise ValueError(f"ticker {ticker!r}: entry must be an object")
        clean = {k: v for k, v in entry.items() if k not in HOLDOUT_METADATA_KEYS}
        leaked = [k for k in clean if "holdout" in k.lower()]
        if leaked:
            raise ValueError(
                f"ticker {ticker!r}: holdout-derived keys present in fit targets: {leaked}"
            )
        for required in ("log_return", "realized_vol_annualized", "abs_return_autocorr", "hill_tail_index"):
            if required not in clean:
                raise ValueError(f"ticker {ticker!r}: missing required block {required!r}")
        tickers[str(ticker)] = clean
    return {"tickers": tickers, "source": str(p), "fit_period": fit_period}
