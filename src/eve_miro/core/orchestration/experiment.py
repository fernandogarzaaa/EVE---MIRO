"""Load and represent ExperimentSpec YAML.

Old historical-replay scenario YAML remains loadable via
`eve_miro.core.simulation.scenarios.load_scenario`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from eve_miro.config import EXPERIMENTS_DIR
from eve_miro.core.world.temporal import as_utc


def parse_horizon(value: str | int | float | None, default: int = 24) -> int:
    if value is None:
        return default
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(1, int(value))
    s = str(value).strip().lower()
    if s.endswith("h"):
        return max(1, int(float(s[:-1])))
    if s.endswith("m"):
        return max(1, int(round(float(s[:-1]) / 60.0)))
    try:
        return max(1, int(float(s)))
    except ValueError:
        return default


class ObservationSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    location: str = "metro_manila"
    information_cutoff: str


class InitializationSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    world_state: str = "observed"


class SimulationSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    engine: str = "mirofish"
    agents: int = 80
    horizon: str = "24h"
    seeds: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5])


class ExperienceSpec(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    engine: str = "eve"
    should_validate: bool = Field(default=True, alias="validate")
    counterfactuals: bool = True


class ScenarioSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    intervention: dict[str, Any] | None = None


class EvaluationSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reality_source: str = "observed"
    metrics: list[str] = Field(
        default_factory=lambda: ["mae", "brier", "calibration", "spatial_error", "temporal_error"]
    )


class ExperimentBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    observation: ObservationSpec
    initialization: InitializationSpec = Field(default_factory=InitializationSpec)
    simulation: SimulationSpec = Field(default_factory=SimulationSpec)
    experience: ExperienceSpec = Field(default_factory=ExperienceSpec)
    scenarios: list[ScenarioSpec] = Field(default_factory=list)
    evaluation: EvaluationSpec = Field(default_factory=EvaluationSpec)

    @property
    def cutoff(self) -> datetime:
        return as_utc(self.observation.information_cutoff)

    @property
    def horizon_hours(self) -> int:
        return parse_horizon(self.simulation.horizon)

    @property
    def agents(self) -> int:
        return int(self.simulation.agents)

    @property
    def seeds(self) -> list[int]:
        return list(self.simulation.seeds)


class ExperimentSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    experiment: ExperimentBody
    path: str | None = None

    @property
    def id(self) -> str:
        return self.experiment.id

    @property
    def cutoff(self) -> datetime:
        return self.experiment.cutoff

    @property
    def horizon_hours(self) -> int:
        return self.experiment.horizon_hours

    @property
    def agents(self) -> int:
        return self.experiment.agents

    @property
    def seeds(self) -> list[int]:
        return self.experiment.seeds

    @property
    def scenarios(self) -> list[ScenarioSpec]:
        return self.experiment.scenarios


def resolve_experiment_path(path_or_id: str | Path | None = None) -> Path:
    default = EXPERIMENTS_DIR / "typhoon" / "typhoon_manila_closed_loop.yaml"
    if path_or_id is None:
        return default
    raw = Path(str(path_or_id))
    if raw.exists():
        return raw
    name = raw.name
    stem = name[: -len(raw.suffix)] if raw.suffix in {".yaml", ".yml"} else name
    typhoon = EXPERIMENTS_DIR / "typhoon"
    for cand in (
        typhoon / name,
        typhoon / f"{stem}.yaml",
        typhoon / f"{stem}.yml",
        EXPERIMENTS_DIR / "historical-replay" / f"{stem}.yaml",
    ):
        if cand.exists() and cand.suffix in {".yaml", ".yml"}:
            # historical-replay files are Scenario YAML, not ExperimentSpec
            if "historical-replay" in str(cand):
                continue
            return cand
    if typhoon.is_dir():
        for cand in sorted(typhoon.glob("*.yaml")):
            data = yaml.safe_load(cand.read_text()) or {}
            body = data.get("experiment") or {}
            if body.get("id") == str(path_or_id) or cand.stem == stem:
                return cand
    raise FileNotFoundError(f"experiment not found: {path_or_id}")


def load_experiment(path_or_id: str | Path | None = None) -> ExperimentSpec:
    path = resolve_experiment_path(path_or_id)
    data = yaml.safe_load(path.read_text()) or {}
    if "experiment" not in data:
        raise ValueError(f"{path} is not an ExperimentSpec YAML (missing top-level 'experiment')")
    spec = ExperimentSpec.model_validate(data)
    spec.path = str(path)
    return spec


def intervention_timestamp(lead_time_minutes: int, horizon_hours: int) -> str:
    """Warning issued `lead_time` before the end of the horizon."""
    lead_h = float(lead_time_minutes) / 60.0
    warn_h = max(0.0, float(horizon_hours) - lead_h)
    if abs(warn_h - round(warn_h)) < 1e-9:
        return f"+{int(round(warn_h))}h"
    return f"+{warn_h}h"
