"""Omniscience is forbidden: world events are not every agent's memory."""

from __future__ import annotations

from datetime import datetime, timezone

from eve_miro.core.simulation.observation import perceive, perceive_population
from eve_miro.core.simulation.population import Persona, generate_population
from eve_miro.core.world.state import WorldState
from tests.helpers import make_event
import random


def _world(events):
    t = datetime(2024, 11, 1, 0, 0, tzinfo=timezone.utc)
    return WorldState(
        world_id="w_perc",
        timestamp=t,
        information_cutoff=t,
        events=[e.id for e in events],
    )


def test_gdelt_like_news_is_not_in_every_agent_observed_events():
    news = make_event(
        "gdelt:typhoon-headline",
        "2024-11-01T00:00:00Z",
        event_type="news.article",
        provider="gdelt",
        payload={"title": "Typhoon nears Metro Manila"},
        lat=14.6,
        lon=121.0,
    )
    weather = make_event(
        "wx-manila-0",
        "2024-11-01T00:00:00Z",
        event_type="weather.hourly",
        provider="openmeteo",
        payload={"wind_speed_10m": 12.0},
        lat=14.6,
        lon=121.0,
    )
    events = [news, weather]
    world = _world(events)
    rng = random.Random(1)
    personas = generate_population(24, rng, lat=14.5995, lon=120.9842)
    observations = perceive_population(personas, world, events)

    news_seen = [obs for obs in observations.values() if news.id in obs.observed_events]
    assert len(observations) == 24
    assert len(news_seen) < 24, "GDELT-like news must not be in every agent's observed_events"
    assert len(news_seen) < len(observations)

    withheld = [obs for obs in observations.values() if news.id in obs.withheld_event_ids]
    assert withheld, "some agents must have the news withheld"
    for obs in withheld:
        assert obs.uncertainty > 0
        assert news.id not in obs.accessible_information.get("event_ids", [])


def test_accessible_information_is_a_subset_and_weather_is_local():
    weather_mnl = make_event(
        "wx-mnl",
        "2024-11-01T00:00:00Z",
        event_type="weather.hourly",
        payload={"wind_speed_10m": 18.0},
        lat=14.6,
        lon=121.0,
        provider="openmeteo",
    )
    news = make_event(
        "gdelt:only-some",
        "2024-11-01T00:00:00Z",
        event_type="news.article",
        provider="gdelt",
        payload={"title": "headline"},
        lat=14.6,
        lon=121.0,
    )
    events = [weather_mnl, news]
    world = _world(events)

    manila = Persona(
        agent_id="persona_mnl",
        age_band="18-34",
        household_size=3,
        vehicle_access=True,
        risk_aversion=0.4,
        mobility_score=0.7,
        shelter_access=True,
        lat=14.60,
        lon=120.99,
    )
    davao = Persona(
        agent_id="persona_dvo",
        age_band="35-54",
        household_size=4,
        vehicle_access=False,
        risk_aversion=0.5,
        mobility_score=0.4,
        shelter_access=True,
        lat=7.07,
        lon=125.61,
    )
    obs_mnl = perceive(manila, world, events)
    obs_dvo = perceive(davao, world, events)

    assert weather_mnl.id in obs_mnl.observed_events
    assert weather_mnl.id not in obs_dvo.observed_events
    assert weather_mnl.id in obs_dvo.withheld_event_ids
    assert obs_dvo.uncertainty > 0
    # accessible_information is a subset — never the full event id list for Davao
    acc_ids = set(obs_dvo.accessible_information.get("event_ids") or [])
    assert news.id not in acc_ids or weather_mnl.id not in acc_ids
    assert set(world.events) - acc_ids
