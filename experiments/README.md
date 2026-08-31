# Experiments

Scenario YAML lives under `historical-replay/`. The default first-domain
scenario is `typhoon_manila_001.yaml` (Philippines / Metro Manila).

Do not treat SIMULATED output as OBSERVED. Historical replay refuses any
event after `information_cutoff` (no future leakage).

Second domain (finance) is stubbed via the CoinGecko provider — not a
scenario YAML in v1.

Closed-loop ExperimentSpec YAML lives under `typhoon/`
(`typhoon_manila_closed_loop.yaml`). That file is loaded by
`load_experiment`; historical-replay files stay on `load_scenario`.
