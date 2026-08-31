"""Tiny memory budget over validated experiences."""

from __future__ import annotations

from eve_miro.core.experience.validation import ValidatedExperience


def select_by_budget(experiences: list[ValidatedExperience], budget: int) -> list[ValidatedExperience]:
    ranked = sorted(experiences, key=lambda e: (e.learning_value * e.confidence), reverse=True)
    # budget is a token-ish cap; v1 treats it as max items * 256
    cap = max(1, budget // 256)
    return ranked[:cap]
