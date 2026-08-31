"""Helpers to align predicted vs observed numeric series by timestamp."""

from __future__ import annotations


from eve_miro.core.world.temporal import as_utc, iso


def align_series(
    pred_times: list[str],
    pred_values: list[float],
    obs_times: list[str],
    obs_values: list[float],
) -> tuple[list[float], list[float], list[str]]:
    obs_map = {iso(as_utc(t)): v for t, v in zip(obs_times, obs_values)}
    aligned_p: list[float] = []
    aligned_o: list[float] = []
    times: list[str] = []
    for t, v in zip(pred_times, pred_values):
        key = iso(as_utc(t))
        if key in obs_map and v is not None and obs_map[key] is not None:
            aligned_p.append(float(v))
            aligned_o.append(float(obs_map[key]))
            times.append(key)
    return aligned_p, aligned_o, times
