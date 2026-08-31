"""Topic names. Redpanda is optional in compose comments; v1 uses the in-process bus."""

TOPICS = {
    "world.events": "eve.world.events",
    "world.snapshots": "eve.world.snapshots",
    "simulation.steps": "eve.simulation.steps",
    "simulation.actions": "eve.simulation.actions",
    "experience.candidates": "eve.experience.candidates",
    "evaluation.results": "eve.evaluation.results",
    "reliability": "eve.reliability",
}
