# Experience

EVE sits behind the `ExperienceEngine` protocol. The default runtime still
uses `StubExperienceEngine` underneath `EVEExperienceEngine` until
`EVE_MIRO_ENGINES=in-tree` and the CLI can actually run. Tests never need
LLM keys or a node build.

## Layers

- `agent` — one synthetic persona's action/outcome
- `population` — mobility aggregate
- `simulator_vs_reality` — predicted vs observed series (`WorldModelExperience` is an alias; the old name still works)

## Graph

`ExperienceGraph` tracks artifact state:

`CANDIDATE` → `VALIDATED` → `REPLICATED` (second similar run) /
`CONFLICTING` (contradicting metric) / `GENERALIZED` / `RETAINED` /
`REJECTED`

## Closed loop

`miro_to_eve.py` is the only path from simulation traces to EVE:
`AgentTrajectory` list → `Trajectory` → `ExperienceEngine.observe` /
`validate`. EVE does not import MiroFish internals.

Artifacts returned by validate are **memory/context** for the next
seed/run (`artifacts=` on the simulation engine). They are never claimed
as weight updates.
