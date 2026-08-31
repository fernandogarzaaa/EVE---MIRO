from __future__ import annotations

import json
from pathlib import Path

from eve_miro.core.evaluation.reality_check import Evaluation
from eve_miro.core.experience.candidates import ExperienceCandidate
from eve_miro.core.experience.validation import ValidatedExperience
from eve_miro.core.simulation.engine import Simulation, SimulationResult
from eve_miro.core.world.events import WorldEvent
from eve_miro.core.world.state import WorldState


def schema_map() -> dict[str, dict]:
    return {
        "world-event": WorldEvent.model_json_schema(),
        "world-state": WorldState.model_json_schema(),
        "experience": ValidatedExperience.model_json_schema(),
        "experience-candidate": ExperienceCandidate.model_json_schema(),
        "simulation": Simulation.model_json_schema(),
        "simulation-result": SimulationResult.model_json_schema(),
        "evaluation": Evaluation.model_json_schema(),
    }


def export_schemas(directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name, schema in schema_map().items():
        path = directory / f"{name}.json"
        path.write_text(json.dumps(schema, indent=2))
        written.append(path)
    return written
