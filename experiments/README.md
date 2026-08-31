# Experiments

Scenario YAML lives under `historical-replay/`. The default first-domain
scenario is `typhoon_manila_001.yaml` (Philippines / Metro Manila).

Do not treat SIMULATED output as OBSERVED. Historical replay refuses any
event after `information_cutoff` (no future leakage).

Second domain (finance) is stubbed via the CoinGecko provider — not a
scenario YAML in v1.
