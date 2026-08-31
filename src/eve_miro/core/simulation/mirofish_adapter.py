"""In-tree MiroFish adapter behind SimulationEngine.

Talks to the real Flask app at ``MIROFISH_URL`` (default http://127.0.0.1:5001)
via ``mirofish_client``. When ``EVE_MIRO_ENGINES`` is not ``stub``, missing
keys or HTTP failure raise ``EngineNotConfigured`` — never ``StubSimulationEngine``.
All outputs are SIMULATED.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from eve_miro.core.simulation.engine import (
    Simulation,
    SimulationResult,
    SimulationStep,
    StubSimulationEngine,
)
from eve_miro.core.simulation.mirofish_client import (
    mirofish_configured as _mirofish_configured,
    missing_mirofish_keys,
    run_mirofish_simulation,
)
from eve_miro.core.simulation.scenarios import Scenario
from eve_miro.core.world.state import Population, WorldState
from eve_miro.errors import EngineNotConfigured
from eve_miro.paths import mirofish_root


def in_tree_available() -> bool:
    """True when the first-party MiroFish tree is present in this repo."""
    return (mirofish_root() / "backend" / "app").is_dir()


# Re-export: callers/tests keep using this name.
__all__ = ["MiroFishEngine", "in_tree_available", "_mirofish_configured"]


class MiroFishEngine:
    """SimulationEngine for the in-tree MiroFish copy. Fail closed when not stub."""

    name = "mirofish"

    def __init__(
        self,
        scenario: Scenario | None = None,
        *,
        artifacts: list[dict[str, Any]] | None = None,
        url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        import os

        self.scenario = scenario
        self.artifacts = list(artifacts or [])
        env_url = os.environ.get("MIROFISH_URL", "").strip() or None
        self.url = url if url is not None else env_url
        self.timeout = timeout
        # Local initialize only (personas / Simulation shell). Never used for run().
        self._shell = StubSimulationEngine(scenario, artifacts=self.artifacts)
        self.last_notes: str | None = None

    @property
    def using_remote(self) -> bool:
        return bool(self.url)

    async def initialize(self, world: WorldState, population: Population) -> Simulation:
        return await self._shell.initialize(world, population)

    async def step(self, simulation: Simulation) -> SimulationStep:
        raise EngineNotConfigured("MiroFishEngine does not support step(); use run() against the Flask app")

    async def run(self, simulation: Simulation, until: datetime) -> SimulationResult:
        if not in_tree_available() and not self.url:
            raise EngineNotConfigured(
                "in-tree MiroFish is missing; expected mirofish/backend/app"
            )
        if not _mirofish_configured():
            from eve_miro.core.simulation.mirofish_client import _require_configured

            _require_configured()
        try:
            result = await run_mirofish_simulation(
                simulation, until, url=self.url, timeout=self.timeout
            )
        except EngineNotConfigured:
            raise
        self.last_notes = "mirofish"
        result.summary["engine"] = "mirofish"
        return result
