# Evaluation

Reality check compares a SIMULATED predicted series against OBSERVED values.
Kinds are never mixed.

Implemented metrics (not comments), in `core/evaluation/metrics.py`:

- MAE, RMSE, MAPE (fraction, zeros in observed skipped)
- Event timing error (minutes)
- Brier score, log loss (probabilities clipped to `(1e-15, 1-1e-15)`), ECE (N bins)
- IoU (axis-aligned boxes `[x1,y1,x2,y2]`, or 1D 0/1 masks)
- Geographic distance (haversine, km) and track divergence (mean haversine)
- Discrete KL and Jensen–Shannon (epsilon smoothing, natural log)
- 1-Wasserstein (sorted samples / quantile functions)

`reality_check` returns a **bundle**:

- point: mae / rmse / mape
- probabilistic: brier / log_loss / ece (when probabilities are present)
- spatial: haversine / iou / track_divergence (when coords, boxes, or tracks are present)
- temporal: timing error

If a domain has no observations, reliability reports **do not trust this domain**.

Calibration is not yet established for v1. Outputs are scenario projections.

## Source confidence (never an LLM)

`source_confidence` is a clipped weighted mean of **measurable** fields only:

```
source_confidence =
    0.25 * reliability
  + 0.20 * freshness
  + 0.20 * completeness
  + 0.20 * cross_source_agreement
  + 0.15 * historical_accuracy
```

Each input is in `[0, 1]`. Callers map age, completeness flags, agreement rates, and
historical MAE/Brier onto that scale. The function never reads free text and never
calls a model. If any of the five fields is missing, confidence is not invented
(`None`).

## Provenance

Every `Evaluation` carries a provenance graph so `evaluation.trace()` walks
conclusion → simulation/state → events → source providers.

## Closed loop, Reality Ledger, Trust Profile

`ClosedLoop` runs `WorldState(t0)` (OBSERVED, cutoff-bounded) through a
MiroFish-shaped sim and EVE, then scores against later-observed
`WorldState(t1)` (openmeteo archive fixture split at the cutoff).

Evaluation is on the **distribution across seeds** (mean, variance,
interval), not a single run treated as truth.

`RealityAligner` matches predicted `wind_speed_10m` (and congestion /
evacuation rate when present) to observed weather. Input provenance is
carried so FORECAST-based predictions are tagged differently from
OBSERVED-based. Spatial error is haversine kilometres when coordinates
exist.

`RealityLedger` stores `PredictionRecord`s: model, seed (null when
aggregated), cutoff, source versions, provenance kinds of inputs, MAE,
and `CORRECT` / `INCORRECT` / `PENDING` from known numeric series.

`TrustProfile` (`GET /trust-profile`) is richer than `GET /reliability`
(which is kept). Per domain (weather, mobility, population, news) it
emits a score and a recommendation; low scores are **DO_NOT_USE**.
