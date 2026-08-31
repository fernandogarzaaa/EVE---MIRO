"""Synthetic statistical personas. Never a named real person."""

from __future__ import annotations

import random
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

AGE_BANDS = ("0-17", "18-34", "35-54", "55-74", "75+")
# Approximate Metro Manila household / mobility mix — statistical, not individuals.
AGE_WEIGHTS = (0.28, 0.30, 0.24, 0.14, 0.04)


class Persona(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str
    age_band: str
    household_size: int
    vehicle_access: bool
    risk_aversion: float
    mobility_score: float
    shelter_access: bool
    lat: float
    lon: float
    role: str = "civilian"
    notes: str = "Synthetic statistical persona. Not a real person."


def generate_population(
    n: int,
    rng: random.Random,
    *,
    lat: float = 14.5995,
    lon: float = 120.9842,
    role: str = "civilian",
) -> list[Persona]:
    people: list[Persona] = []
    notes = (
        "Synthetic statistical investor persona. Not a real person. Public rates only."
        if role == "investor"
        else "Synthetic statistical persona. Not a real person."
    )
    for i in range(n):
        age = rng.choices(AGE_BANDS, weights=AGE_WEIGHTS, k=1)[0]
        people.append(
            Persona(
                agent_id=f"persona_{i:04d}",
                age_band=age,
                household_size=rng.randint(1, 8),
                vehicle_access=rng.random() < 0.35,
                risk_aversion=round(rng.random(), 3),
                mobility_score=round(rng.uniform(0.2, 1.0), 3),
                shelter_access=rng.random() < 0.55,
                lat=lat + rng.uniform(-0.12, 0.12),
                lon=lon + rng.uniform(-0.12, 0.12),
                role=role,
                notes=notes,
            )
        )
    return people


def population_summary(people: list[Persona]) -> dict[str, Any]:
    n = max(len(people), 1)
    return {
        "synthetic_n": len(people),
        "vehicle_access_rate": round(sum(1 for p in people if p.vehicle_access) / n, 3),
        "shelter_access_rate": round(sum(1 for p in people if p.shelter_access) / n, 3),
        "mean_risk_aversion": round(sum(p.risk_aversion for p in people) / n, 3),
        "disclaimer": "Synthetic statistical personas grounded in public demographic rates. Not real people.",
    }
