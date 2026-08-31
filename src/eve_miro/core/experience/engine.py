"""ExperienceEngine protocol. EVE stays behind this interface; v1 ships a stub."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from eve_miro.core.experience.candidates import ExperienceCandidate, Trajectory
from eve_miro.core.experience.counterfactual import Counterfactual
from eve_miro.core.experience.memory import select_by_budget
from eve_miro.core.experience.transfer import evaluate_transfer
from eve_miro.core.experience.validation import TransferResult, ValidatedExperience
from eve_miro.core.world.events import ProvenanceKind


@runtime_checkable
class ExperienceEngine(Protocol):
    async def observe(self, trajectory: Trajectory) -> list[ExperienceCandidate]: ...

    async def validate(self, experience: ExperienceCandidate) -> ValidatedExperience: ...

    async def select(self, experiences: list[ValidatedExperience], budget: int) -> list[ValidatedExperience]: ...

    async def generate_counterfactual(self, experience: ValidatedExperience) -> list[Counterfactual]: ...

    async def evaluate_transfer(self, experience: ValidatedExperience, context: dict[str, Any]) -> TransferResult: ...


class StubExperienceEngine:
    """Deterministic stand-in for EVE. Not the real EVE model."""

    name = "eve_stub"

    async def observe(self, trajectory: Trajectory) -> list[ExperienceCandidate]:
        actions = trajectory.actions
        stuck = [a for a in actions if a.get("action") == "stuck"]
        evac = [a for a in actions if a.get("action") == "evacuate"]
        warning_hours = [a["hour"] for a in actions if a.get("warning_active")]
        cong = [float(a.get("congestion") or 0) for a in actions]
        peak_c = max(cong) if cong else 0.0
        first_warn = min(warning_hours) if warning_hours else None
        candidates = [
            ExperienceCandidate(
                id=f"exp_agent_{trajectory.simulation_id}",
                agent_id=stuck[0]["agent_id"] if stuck else (evac[0]["agent_id"] if evac else None),
                episode_id="episode_81",
                layer="agent",
                context={"high_traffic_density": peak_c > 0.35, "peak_congestion": peak_c},
                action="evacuate" if evac else "stay",
                observation={"stuck_n": len(stuck), "evacuated_n": len(evac)},
                outcome="congestion_blocked" if stuck else "evacuated",
                temporal_window={"first_warning_hour": first_warn},
            ),
            ExperienceCandidate(
                id=f"exp_pop_{trajectory.simulation_id}",
                episode_id="episode_81",
                layer="population",
                context={"population_actions": len(actions)},
                observation={"stuck_n": len(stuck), "evacuated_n": len(evac), "peak_congestion": peak_c},
                outcome="population_mobility",
            ),
            ExperienceCandidate(
                id=f"exp_simreality_{trajectory.simulation_id}",
                episode_id="episode_81",
                layer="simulator_vs_reality",
                context={"series": list(trajectory.predicted_series.keys())},
                prediction={"wind_speed_10m": trajectory.predicted_series.get("wind_speed_10m", [])},
                outcome="pending_reality_check",
            ),
        ]
        return candidates

    async def validate(self, experience: ExperienceCandidate) -> ValidatedExperience:
        stuck_n = int((experience.observation or {}).get("stuck_n") or 0)
        peak = float((experience.context or {}).get("peak_congestion") or 0)
        artifact = None
        if experience.layer in {"agent", "population"}:
            artifact = {
                "experience": "evacuation warnings arriving after congestion begins are ineffective",
                "conditions": ["high traffic density", "warning delay > 20 minutes"],
                "confidence": 0.91,
                "source": ["episode_81"],
                "provenance_kind": ProvenanceKind.SIMULATED.value,
            }
        cfs = await self.generate_counterfactual(
            ValidatedExperience(
                id=experience.id,
                candidate=experience,
                validity=0.8,
                confidence=0.91,
                learning_value=0.7,
                transferability=0.6,
                retention_score=0.5,
                layer=experience.layer,
            )
        )
        return ValidatedExperience(
            id=experience.id,
            candidate=experience,
            validity=0.88 if stuck_n else 0.7,
            confidence=0.91,
            prediction_error=None,
            learning_value=min(1.0, 0.4 + peak),
            transferability=0.62,
            retention_score=0.7,
            counterfactuals=cfs,
            applicability=["philippines", "typhoon", "metro_manila", "mobility"],
            artifact=artifact,
            layer=experience.layer,
        )

    async def select(self, experiences: list[ValidatedExperience], budget: int) -> list[ValidatedExperience]:
        return select_by_budget(experiences, budget)

    async def generate_counterfactual(self, experience: ValidatedExperience) -> list[Counterfactual]:
        cf = Counterfactual(
            id=f"cf_{experience.id}_early_warning",
            base_experience_id=experience.id,
            intervention="issue evacuation_warning 90 minutes earlier, before congestion onset",
            predicted_delta={"stuck_rate": -0.35, "evacuated_rate": 0.2},
            label="model-generated",
            fact=False,
        )
        cf.assert_not_fact()
        return [cf]

    async def evaluate_transfer(self, experience: ValidatedExperience, context: dict[str, Any]) -> TransferResult:
        return evaluate_transfer(experience, context)
