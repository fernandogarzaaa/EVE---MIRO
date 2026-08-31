"""Scenario YAML loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from eve_miro.config import EXPERIMENTS_DIR
from eve_miro.core.world.temporal import as_utc


class Intervention(BaseModel):
    type: str
    timestamp: str
    coverage: float = 1.0
    extra: dict[str, Any] = Field(default_factory=dict)


class Scenario(BaseModel):
    name: str
    type: str = "typhoon"
    initial_world: dict[str, Any]
    duration: dict[str, Any]
    agents: dict[str, Any]
    conditions: dict[str, Any] = Field(default_factory=dict)
    interventions: list[Intervention] = Field(default_factory=list)
    random_seed: int = 48291
    information_cutoff: str
    path: str | None = None
    disclaimer: str = (
        "SIMULATED. Synthetic statistical personas, not real people. "
        "Outputs are scenario projections under stated assumptions, never 'the future is'."
    )

    @property
    def population(self) -> int:
        return int(self.agents.get("population", 200))

    @property
    def simulated_hours(self) -> int:
        return int(self.duration.get("simulated_hours", 24))

    @property
    def cutoff(self):
        return as_utc(self.information_cutoff)

    @property
    def origin(self):
        return as_utc(self.initial_world.get("timestamp") or self.information_cutoff)


def load_scenario(path: str | Path | None = None, *, name: str = "typhoon_manila_001") -> Scenario:
    if path is None:
        path = EXPERIMENTS_DIR / "historical-replay" / f"{name}.yaml"
    path = Path(path)
    data = yaml.safe_load(path.read_text())
    data["path"] = str(path)
    return Scenario.model_validate(data)
