"""In-tree EVE adapter behind ExperienceEngine.

Invokes ``eve trajectory --stdin`` (HeuristicCognition). There is no POST
/validate. Missing CLI raises EngineNotConfigured — never StubExperienceEngine.

Counterfactuals are always labeled model-generated, not fact.
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
from eve_miro.core.experience.eve_cli import eve_trajectory_command
from eve_miro.errors import EngineNotConfigured
from eve_miro.paths import eve_root

_DEFAULT_TIMEOUT = 30.0


def _env(name: str) -> str | None:
    v = os.environ.get(name, "").strip()
    return v or None


def in_tree_available() -> bool:
    """True when the first-party EVE tree is present in this repo."""
    return (eve_root() / "src" / "index.ts").is_file()


def default_eve_bin() -> str | None:
    """Path to the in-tree CLI entry when that file exists."""
    candidate = eve_root() / "bin" / "eve.js"
    return str(candidate) if candidate.is_file() else None


def _eve_can_run() -> bool:
    """True when the in-tree CLI has been built (dist + node_modules)."""
    root = eve_root()
    return (
        (root / "bin" / "eve.js").is_file()
        and (root / "dist" / "cli" / "main.js").is_file()
        and (root / "node_modules").is_dir()
    )


class EVEExperienceEngine:
    """ExperienceEngine for the in-tree EVE copy. Fail closed on validate()."""

    name = "eve"

    def __init__(
        self,
        *,
        url: str | None = None,
        bin_path: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.url = url if url is not None else _env("EVE_URL")
        explicit_bin = bin_path if bin_path is not None else _env("EVE_BIN")
        self.bin = explicit_bin or default_eve_bin()
        self._invoke_bin = bool(explicit_bin)
        self.timeout = float(timeout if timeout is not None else _DEFAULT_TIMEOUT)
        self._local_heuristic = StubExperienceEngine()
        self.last_notes: str | None = None

    @property
    def using_remote(self) -> bool:
        return bool(self.url)

    async def observe(self, trajectory: Trajectory) -> list[ExperienceCandidate]:
        """Layer extraction is a local heuristic. EVE CLI runs at validate()."""
        cands = await self._local_heuristic.observe(trajectory)
        for cand in cands:
            prov = dict(cand.provenance or {})
            prov["kind"] = ProvenanceKind.SIMULATED.value
            prov["engine"] = "local-heuristic"
            prov["notes"] = (
                "Candidate extraction is a local heuristic. "
                "EVE CLI (eve.js trajectory) runs at validate(), not observe()."
            )
            cand.provenance = prov
        return cands

    async def validate(self, experience: ExperienceCandidate) -> ValidatedExperience:
        try:
            remote = self._bin_validate(experience)
        except EngineNotConfigured:
            raise
        except FileNotFoundError as exc:
            raise EngineNotConfigured("EVE CLI is not built") from exc
        except Exception as exc:
            raise EngineNotConfigured(f"eve trajectory failed: {exc}") from exc
        mapped = self._map_remote(experience, remote)
        if mapped is None:
            raise EngineNotConfigured("eve trajectory returned unmappable JSON")
        self.last_notes = "eve"
        return mapped

    async def select(self, experiences: list[ValidatedExperience], budget: int) -> list[ValidatedExperience]:
        chosen = await self._local_heuristic.select(experiences, budget)
        self.last_notes = "local-heuristic-select"
        return chosen

    async def generate_counterfactual(self, experience: ValidatedExperience) -> list[Counterfactual]:
        cfs = await self._local_heuristic.generate_counterfactual(experience)
        self.last_notes = "local-heuristic-counterfactual"
        return cfs

    async def evaluate_transfer(self, experience: ValidatedExperience, context: dict[str, Any]) -> TransferResult:
        result = await self._local_heuristic.evaluate_transfer(experience, context)
        note = (result.notes or "").strip()
        extra = "local-heuristic transfer; EVE CLI is used at validate()."
        result.notes = f"{note} {extra}".strip() if note else extra
        self.last_notes = "local-heuristic-transfer"
        return result

    def _bin_validate(self, experience: ExperienceCandidate) -> dict[str, Any]:
        import subprocess

        raw = json.dumps(experience.model_dump(mode="json")).encode("utf-8")
        proc = subprocess.run(
            eve_trajectory_command(),
            input=raw,
            capture_output=True,
            timeout=self.timeout,
            check=False,
        )
        if proc.returncode != 0:
            raise EngineNotConfigured("eve trajectory failed")
        try:
            data = json.loads(proc.stdout.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise EngineNotConfigured("eve trajectory returned non-JSON") from exc
        if not isinstance(data, dict):
            raise EngineNotConfigured("eve trajectory response is not an object")
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
