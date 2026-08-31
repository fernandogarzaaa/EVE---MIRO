"""Domain errors. Mixing provenance kinds or leaking the future is a hard failure."""


class EveMiroError(Exception):
    """Base error."""


class ProvenanceError(EveMiroError):
    """Raised when provenance kinds are mixed or simulated data is treated as observed."""


class FutureLeakageError(EveMiroError):
    """Raised when an event or state would use information after information_cutoff."""


class QualityError(EveMiroError):
    """Raised when an event fails the quality pipeline."""


class ReplayError(EveMiroError):
    """Raised when historical replay is asked to consume post-cutoff events."""


class EngineNotConfigured(EveMiroError):
    """Raised when in-tree MiroFish/EVE cannot run. Fail closed — never silent stub."""


class ProviderError(EveMiroError):
    """Raised when a live provider fetch fails. Fail closed — never silent []."""
