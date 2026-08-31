"""In-process pub/sub used when Redpanda is not running."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

Handler = Callable[[str, Any], None]


class InProcessBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)
        self._log: list[tuple[str, Any]] = []

    def publish(self, topic: str, message: Any) -> None:
        self._log.append((topic, message))
        for handler in list(self._subs.get(topic, [])):
            handler(topic, message)

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subs[topic].append(handler)

    def history(self, topic: str | None = None) -> list[tuple[str, Any]]:
        if topic is None:
            return list(self._log)
        return [x for x in self._log if x[0] == topic]


BUS = InProcessBus()
