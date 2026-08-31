# Experience

EVE sits behind the `ExperienceEngine` protocol. `get_experience_engine()`
returns `StubExperienceEngine` only when `EVE_MIRO_ENGINES=stub` (pytest).
Otherwise `EVEExperienceEngine.validate()` invokes `eve trajectory --stdin`
(HeuristicCognition). There is no `POST /validate`. A missing CLI raises
`EngineNotConfigured` — never a silent stub. Tests mock the process or force
stub mode and never need a node build.

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
