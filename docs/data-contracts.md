# Data contracts

JSON Schema is generated from pydantic v2 models:

- `schemas/world-event.json`
- `schemas/world-state.json`
- `schemas/experience.json`
- `schemas/simulation.json`
- `schemas/evaluation.json`

Regenerate: `make schemas`.

`WorldEvent` fields: id, source, observed_at, ingested_at, location?, entity?,
event_type, payload, provenance, temporal, information_cutoff?.

`WorldState` fields: world_id, timestamp, information_cutoff, geography,
environment, economy, infrastructure, mobility, information, population,
events, provenance_graph.

Every simulation and every world state carries `information_cutoff`.
