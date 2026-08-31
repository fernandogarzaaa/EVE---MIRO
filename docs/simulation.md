# Simulation

`StubSimulationEngine` is a tiny Philippines typhoon-style run:

- Synthetic statistical personas (not real people; public demographic rates only)
- Seeded RNG
- Interventions from scenario YAML (e.g. `evacuation_warning` at +6h, coverage 0.8)
- Agent actions `stay | evacuate | shelter | stuck` with congestion
- All outputs labeled SIMULATED

Population: 200 in tests, 1000 in `typhoon_manila_001` (not 10k).

Historical replay (`core/simulation/replay.py`) refuses any event after
`information_cutoff`.
