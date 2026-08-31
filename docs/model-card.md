# Model card — typhoon_manila_001

**Type:** scenario projection under a stub mobility/weather engine.
**Not:** a forecast of a real typhoon, and not a statement that “the future is…”.

## Intended use

Exercise the EVE-MIRO loop on a Philippines / Metro Manila bounding box:
ingest public weather and earthquake fixtures, reconstruct WorldState(t),
run a seeded synthetic-population simulation, emit experiences, compare
predicted wind to observed wind when timestamps align.

## Assumptions

- Agents are synthetic statistical personas (age bands, household size,
  vehicle/shelter access, risk aversion). They are not named real people.
- Typhoon wind follows a smooth unimodal curve peaking at hour 36 (~110 km/h).
- An official evacuation warning at T+6h reaches 80% of agents.
- Congestion reduces evacuation success; a late warning after congestion
  onset is modeled as ineffective.
- Open-Meteo archive hours are OBSERVED; forecast endpoint hours are FORECAST.
- USGS FDSN events in the PH bbox are OBSERVED.

## Limitations

- No hydrodynamic storm surge, no building stock, no real road graph.
- Mobility (OpenSky/AIS) is a stub in v1.
- Calibration is **not yet established**. MAE/RMSE on aligned series are
  diagnostic, not a claim of skill.
- 72 simulated hours × 1000 agents is a toy scale.
- Counterfactuals are **model-generated, not fact**.

## Outputs

Labeled SIMULATED. Use them to measure prediction error against OBSERVED
reality, then feed that error back into the experience engine. Do not
publish them as observations.
