"""Transfer evaluation placeholder used by the stub engine."""

from __future__ import annotations

from typing import Any

from eve_miro.core.experience.validation import TransferResult, ValidatedExperience


def evaluate_transfer(experience: ValidatedExperience, context: dict[str, Any]) -> TransferResult:
    region = str(context.get("region", "philippines"))
    ok = region in {"philippines", "metro_manila"} and experience.transferability >= 0.5
    return TransferResult(
        experience_id=experience.id,
        context=context,
        transferable=ok,
        score=experience.transferability if ok else experience.transferability * 0.3,
        notes="Transfer judged only for the PH typhoon mobility/weather domain in v1.",
    )
