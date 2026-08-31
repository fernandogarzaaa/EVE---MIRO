"""EVE adapter. Not a clone — HTTP/CLI client behind ExperienceEngine.

Fernando's experience-validation-engine is a TypeScript UX/cognitive simulator
with an observe → predict → decide loop. We map ExperienceCandidate onto that
loop conceptually and never vendor the repo.

If EVE_URL is set: POST {EVE_URL}/validate with the candidate JSON.
If EVE_BIN is set: invoke the binary with JSON on stdin (timeout-fast).
If neither is set, every call delegates to StubExperienceEngine.

On error, fall back to the stub. Counterfactuals are always labeled
model-generated, not fact. Mapped fields: validity, confidence,
prediction_error, learning_value, transferability, retention_score,
counterfactuals, applicability.
"""

from __future__ import annotations

import json
import os
from typing import Any

from eve_miro.core.experience.candidates import ExperienceCandidate, Trajectory
from eve_miro.core.experience.counterfactual import Counterfactual
from eve_miro.core.experience.engine import StubExperienceEngine
from eve_miro.core.experience.validation import TransferResult, ValidatedExperience
from eve_miro.core.world.events import ProvenanceKind

_DEFAULT_TIMEOUT = 1.5


def _env(name: str) -> str | None:
    v = os.environ.get(name, "").strip()
    return v or None


class EVEExperienceEngine:
    """ExperienceEngine that optionally calls a replaceable EVE service."""

    name = "eve"

    def __init__(
        self,
        *,
        url: str | None = None,
        bin_path: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self.url = url if url is not None else _env("EVE_URL")
        self.bin = bin_path if bin_path is not None else _env("EVE_BIN")
        self.timeout = timeout
        self._stub = StubExperienceEngine()
        self.last_notes: str | None = None

    @property
    def using_remote(self) -> bool:
        return bool(self.url) or bool(self.bin)

    async def observe(self, trajectory: Trajectory) -> list[ExperienceCandidate]:
        # Observation extraction is local; EVE's loop is observe→predict→decide
        # at validate time. Always emit the three layers via the stub.
        return await self._stub.observe(trajectory)

    async def validate(self, experience: ExperienceCandidate) -> ValidatedExperience:
        if self.url:
            try:
                remote = await self._post_validate(experience)
                mapped = self._map_remote(experience, remote)
                if mapped is not None:
                    self.last_notes = "eve"
                    return mapped
                raise ValueError("unmappable eve response")
            except Exception:
                self.last_notes = "eve_unavailable"
                return await self._stub.validate(experience)
        if self.bin:
            try:
                remote = self._bin_validate(experience)
                mapped = self._map_remote(experience, remote)
                if mapped is not None:
                    self.last_notes = "eve"
                    return mapped
                raise ValueError("unmappable eve binary response")
            except Exception:
                self.last_notes = "eve_unavailable"
                return await self._stub.validate(experience)
        return await self._stub.validate(experience)

    async def select(self, experiences: list[ValidatedExperience], budget: int) -> list[ValidatedExperience]:
        return await self._stub.select(experiences, budget)

    async def generate_counterfactual(self, experience: ValidatedExperience) -> list[Counterfactual]:
        return await self._stub.generate_counterfactual(experience)

    async def evaluate_transfer(self, experience: ValidatedExperience, context: dict[str, Any]) -> TransferResult:
        return await self._stub.evaluate_transfer(experience, context)

    async def _post_validate(self, experience: ExperienceCandidate) -> dict[str, Any]:
        import httpx

        base = str(self.url).rstrip("/")
        payload = experience.model_dump(mode="json")
        timeout = httpx.Timeout(self.timeout)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{base}/validate", json=payload)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("eve response is not an object")
            return data

    def _bin_validate(self, experience: ExperienceCandidate) -> dict[str, Any]:
        import subprocess

        raw = json.dumps(experience.model_dump(mode="json")).encode("utf-8")
        proc = subprocess.run(
            [str(self.bin)],
            input=raw,
            capture_output=True,
            timeout=self.timeout,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError("eve_bin_failed")
        data = json.loads(proc.stdout.decode("utf-8") or "{}")
        if not isinstance(data, dict):
            raise ValueError("eve binary response is not an object")
        return data

    def _map_remote(self, experience: ExperienceCandidate, remote: dict[str, Any]) -> ValidatedExperience | None:
        if not remote:
            return None
        cfs_raw = remote.get("counterfactuals") or []
        counterfactuals: list[Counterfactual] = []
        for i, row in enumerate(cfs_raw):
            if not isinstance(row, dict):
                continue
            cf = Counterfactual(
                id=str(row.get("id") or f"cf_{experience.id}_{i}"),
                base_experience_id=experience.id,
                intervention=str(row.get("intervention") or "model-generated intervention"),
                predicted_delta=dict(row.get("predicted_delta") or {}),
                label="model-generated",
                fact=False,
                provenance_kind=ProvenanceKind.SIMULATED,
            )
            cf.assert_not_fact()
            counterfactuals.append(cf)
        if not counterfactuals:
            # Keep the stub's labeled counterfactual so the contract holds.
            counterfactuals = []
        artifact = remote.get("artifact")
        if artifact is not None and not isinstance(artifact, dict):
            artifact = None
        try:
            val = ValidatedExperience(
                id=str(remote.get("id") or experience.id),
                candidate=experience,
                validity=float(remote.get("validity", 0.7)),
                confidence=float(remote.get("confidence", 0.5)),
                prediction_error=(
                    float(remote["prediction_error"]) if remote.get("prediction_error") is not None else None
                ),
                learning_value=float(remote.get("learning_value", 0.5)),
                transferability=float(remote.get("transferability", 0.5)),
                retention_score=float(remote.get("retention_score", 0.5)),
                counterfactuals=counterfactuals,
                applicability=[str(x) for x in (remote.get("applicability") or [])],
                artifact=artifact,
                layer=experience.layer,
                episode_id=experience.episode_id,
            )
        except Exception:
            return None
        if not val.counterfactuals:
            # Fill from stub contract: always model-generated, never fact.
            val.counterfactuals = [
                Counterfactual(
                    id=f"cf_{experience.id}_eve",
                    base_experience_id=experience.id,
                    intervention="model-generated (eve adapter fallback label)",
                    label="model-generated",
                    fact=False,
                )
            ]
            val.counterfactuals[0].assert_not_fact()
        return val
