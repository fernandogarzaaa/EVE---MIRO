# Evaluation

Reality check compares a SIMULATED predicted series against OBSERVED values.

Implemented metrics (not comments):

- MAE
- RMSE
- Event timing error (minutes)
- Brier score (when probabilities are present)

If a domain has no observations, reliability reports **do not trust this domain**.

Calibration is not yet established for v1. Outputs are scenario projections.
