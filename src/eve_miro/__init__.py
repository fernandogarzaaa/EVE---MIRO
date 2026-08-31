"""EVE-MIRO: reality-grounded experiential simulation."""

__version__ = "1.0.0"

from eve_miro.core.world.events import ProvenanceKind, WorldEvent
from eve_miro.core.world.state import WorldState

__all__ = ["__version__", "ProvenanceKind", "WorldEvent", "WorldState"]
