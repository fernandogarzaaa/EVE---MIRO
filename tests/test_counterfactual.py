import pytest

from eve_miro.core.experience.candidates import ExperienceCandidate
from eve_miro.core.experience.engine import StubExperienceEngine
from eve_miro.core.experience.validation import ValidatedExperience


@pytest.mark.asyncio
async def test_counterfactual_labeled_model_generated():
    engine = StubExperienceEngine()
    cand = ExperienceCandidate(
        id="exp_x",
        episode_id="episode_81",
        layer="agent",
        context={"peak_congestion": 0.6},
        observation={"stuck_n": 4},
        outcome="congestion_blocked",
    )
    val = await engine.validate(cand)
    assert val.counterfactuals
    cf = val.counterfactuals[0]
    assert cf.label == "model-generated"
    assert cf.fact is False
    cf.assert_not_fact()
    with pytest.raises(ValueError):
        cf.model_copy(update={"fact": True, "label": "fact"}).assert_not_fact()



@pytest.mark.asyncio
async def test_validated_experience_trace_answers_why():
    engine = StubExperienceEngine()
    cand = ExperienceCandidate(
        id="exp_why",
        episode_id="episode_81",
        layer="agent",
        context={
            "peak_congestion": 0.6,
            "event_ids": ["ev1"],
            "source_providers": ["openmeteo"],
            "world_state_timestamp": "2026-08-31T10:00:00+00:00",
        },
        observation={"stuck_n": 4},
        outcome="congestion_blocked",
    )
    val = await engine.validate(cand)
    nodes = val.trace()
    types = {n.type for n in nodes}
    assert "conclusion" in types
    assert "episode" in types or "experience" in types
    assert val.episode_id == "episode_81"
    _ = ValidatedExperience  # imported for type presence
