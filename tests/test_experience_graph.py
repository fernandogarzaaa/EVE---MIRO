"""Experience graph: CANDIDATE → VALIDATED, CONFLICTING, REPLICATED."""

from __future__ import annotations

from eve_miro.core.experience.graph import ExperienceGraph, ExperienceStatus
from eve_miro.core.experience.layers import SimulatorExperience, WorldModelExperience


def test_candidate_then_validated_then_replicated():
    g = ExperienceGraph()
    a = g.add_candidate(
        "exp_a",
        layer="agent",
        fingerprint="warning-delay",
        artifact={"experience": "late warnings fail", "conditions": ["congestion"]},
    )
    assert a.state is ExperienceStatus.CANDIDATE
    g.mark_validated("exp_a")
    assert g.get("exp_a").state is ExperienceStatus.VALIDATED

    g.add_candidate("exp_b", layer="agent", fingerprint="warning-delay")
    g.mark_validated("exp_b")
    assert g.get("exp_b").state is ExperienceStatus.REPLICATED
    assert "exp_a" in g.get("exp_b").similar_to


def test_conflicting_on_contradicting_metric():
    g = ExperienceGraph()
    g.add_candidate("exp_c", layer="simulator_vs_reality", fingerprint="wind-mae")
    g.mark_validated("exp_c")
    g.get("exp_c").metric_mae = 1.0
    g.add_candidate("exp_d", layer="simulator_vs_reality", fingerprint="wind-mae")
    g.mark_validated("exp_d")
    node = g.maybe_conflict_on_mae("exp_d", 8.0, relative_threshold=0.5)
    assert node.state is ExperienceStatus.CONFLICTING


def test_world_model_experience_is_alias_of_simulator_vs_reality():
    assert WorldModelExperience is SimulatorExperience
