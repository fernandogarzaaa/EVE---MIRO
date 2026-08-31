"""MiroFish adapter. Not a clone — HTTP client behind SimulationEngine.

Typical MiroFish-shaped services (see comments only; we do not vendor the
upstream repo) accept a seed world snapshot plus a prediction requirement and
return a simulated trajectory. Conservative HTTP:

    POST {MIROFISH_URL}/api/predict
    POST {MIROFISH_URL}/simulate
    JSON body: {seed, requirement, cutoff}

If MIROFISH_URL is unset, every call delegates to StubSimulationEngine so
tests pass without the network. On error or timeout the stub is used and
provenance notes record ``mirofish_unavailable``. All outputs are SIMULATED.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from eve_miro.core.simulation.engine import (
    Simulation,
    SimulationResult,
    SimulationStep,
    StubSimulationEngine,
)
from eve_miro.core.simulation.scenarios import Scenario
from eve_miro.core.world.events import ProvenanceKind
from eve_miro.core.world.state import Population, WorldState
from eve_miro.core.world.temporal import iso

# Conservative paths — we do not clone MiroFish to discover a schema.
_REMOTE_PATHS = ("/api/predict", "/simulate", "/api/simulate")
_DEFAULT_TIMEOUT = 1.5


def _env_url() -> str | None:
    v = os.environ.get("MIROFISH_URL", "").strip()
    return v or None


class MiroFishEngine:
    """SimulationEngine that optionally POSTs to a replaceable MiroFish service."""

    name = "mirofish"

    def __init__(
        self,
        scenario: Scenario | None = None,
        *,
        artifacts: list[dict[str, Any]] | None = None,
        url: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self.scenario = scenario
        self.artifacts = list(artifacts or [])
        self.url = (url if url is not None else _env_url()) or None
        self.timeout = timeout
        self._stub = StubSimulationEngine(scenario, artifacts=self.artifacts)
        self.last_notes: str | None = None

    @property
    def using_remote(self) -> bool:
        return bool(self.url)

    async def initialize(self, world: WorldState, population: Population) -> Simulation:
        # Local Simulation object is always built by the stub (same contract).
        return await self._stub.initialize(world, population)

    async def step(self, simulation: Simulation) -> SimulationStep:
        return await self._stub.step(simulation)

    async def run(self, simulation: Simulation, until: datetime) -> SimulationResult:
        if not self.url:
            return await self._stub.run(simulation, until)
        try:
            remote = await self._post_predict(simulation, until)
            mapped = self._map_remote(simulation, remote)
            if mapped is not None:
                self.last_notes = "mirofish"
                mapped.summary["engine"] = "mirofish"
                mapped.summary["provenance_kind"] = ProvenanceKind.SIMULATED.value
                mapped.simulation.provenance_kind = ProvenanceKind.SIMULATED
                return mapped
            raise ValueError("unmappable mirofish response")
        except Exception:
            result = await self._stub.run(simulation, until)
            self.last_notes = "mirofish_unavailable"
            result.summary["engine"] = "stub"
            result.summary["provenance_notes"] = "mirofish_unavailable"
            result.summary["provenance_kind"] = ProvenanceKind.SIMULATED.value
            return result

    async def _post_predict(self, simulation: Simulation, until: datetime) -> dict[str, Any]:
        import httpx

        seed = {
            "world_id": simulation.world_id,
            "simulation_id": simulation.id,
            "snapshot": simulation.world_snapshot,
            "scenario": simulation.scenario_name,
            "scenario_type": simulation.scenario_type,
            "seed": simulation.seed,
            "hours": simulation.hours,
            "population_n": simulation.population_n,
            "interventions": simulation.interventions,
        }
        payload = {
            "seed": seed,
            "requirement": {
                "until": iso(until),
                "kind": ProvenanceKind.SIMULATED.value,
            },
            "cutoff": iso(simulation.information_cutoff),
        }
        base = self.url.rstrip("/")  # type: ignore[union-attr]
        timeout = httpx.Timeout(self.timeout)
        last_exc: Exception | None = None
        async with httpx.AsyncClient(timeout=timeout) as client:
            for path in _REMOTE_PATHS:
                try:
                    response = await client.post(f"{base}{path}", json=payload)
                    if response.status_code < 400:
                        data = response.json()
                        if isinstance(data, dict):
                            return data
                except Exception as exc:
                    last_exc = exc
                    continue
        raise RuntimeError(f"mirofish_unavailable: {last_exc}")

    def _map_remote(self, simulation: Simulation, remote: dict[str, Any]) -> SimulationResult | None:
        series = remote.get("predicted_series") or remote.get("series") or {}
        if isinstance(series, list):
            series = {"value": [float(x) for x in series]}
        if not isinstance(series, dict) or not series:
            prediction = remote.get("prediction")
            if isinstance(prediction, list):
                series = {"value": [float(x) for x in prediction]}
            elif isinstance(prediction, (int, float)):
                series = {"value": [float(prediction)]}
            else:
                return None
        times = [str(t) for t in (remote.get("predicted_times") or remote.get("times") or [])]
        traces = list(remote.get("traces") or [])
        for row in traces:
            if isinstance(row, dict):
                row.setdefault("provenance_kind", ProvenanceKind.SIMULATED.value)
        simulation.status = "completed"
        simulation.provenance_kind = ProvenanceKind.SIMULATED
        summary = dict(remote.get("summary") or {})
        summary["provenance_kind"] = ProvenanceKind.SIMULATED.value
        summary["disclaimer"] = simulation.disclaimer
        summary["engine"] = "mirofish"
        return SimulationResult(
            simulation=simulation,
            traces=traces,
            predicted_series={k: [float(x) for x in v] for k, v in series.items()},
            predicted_times=times,
            summary=summary,
        )
