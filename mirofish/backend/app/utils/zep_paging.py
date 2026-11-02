"""Fetch every Zep Graph node/edge through the 4.0 SDK pager.

The zep-cloud 4.0 ``node.list`` / ``edge.list`` calls return a ``SyncPager``
that transparently follows cursors when iterated, so pagination is a single
materialization instead of manual cursor-header bookkeeping.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from zep_cloud.client import Zep

from .logger import get_logger
from .zep import call_zep_read_with_retry

logger = get_logger("mirofish.zep_paging")

_DEFAULT_PAGE_SIZE = 100
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_RETRY_DELAY = 2.0


def _fetch_page_with_retry(
    api_call: Callable[..., Any],
    *args: Any,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    retry_delay: float = _DEFAULT_RETRY_DELAY,
    page_description: str = "page",
    **kwargs: Any,
) -> Any:
    """Fetch one read-only result with the shared transient-error policy."""

    return call_zep_read_with_retry(
        lambda: api_call(*args, **kwargs),
        operation_name=page_description,
        max_attempts=max_retries,
        initial_delay=retry_delay,
    )


def _fetch_all(
    api_call: Callable[..., Any],
    graph_id: str,
    *,
    item_name: str,
    page_size: int,
    max_items: int | None,
    max_retries: int,
    retry_delay: float,
) -> list[Any]:
    if not 1 <= page_size <= 100:
        raise ValueError("page_size must be between 1 and 100")
    if max_items is not None and max_items < 1:
        raise ValueError("max_items must be at least 1 when provided")

    def fetch_all_pages() -> list[Any]:
        # Materializing inside the retry keeps the transient-error policy
        # covering every page the pager transparently follows.
        return list(api_call(graph_id, page_size=page_size))

    all_items = _fetch_page_with_retry(
        fetch_all_pages,
        max_retries=max_retries,
        retry_delay=retry_delay,
        page_description=f"fetch {item_name} (graph={graph_id})",
    )

    if max_items is not None and len(all_items) > max_items:
        logger.warning(
            "Zep %s pagination reached explicit max_items=%s for graph %s",
            item_name,
            max_items,
            graph_id,
        )
        return all_items[:max_items]
    return all_items


def fetch_all_nodes(
    client: Zep,
    graph_id: str,
    page_size: int = _DEFAULT_PAGE_SIZE,
    max_items: int | None = None,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    retry_delay: float = _DEFAULT_RETRY_DELAY,
) -> list[Any]:
    """Fetch every graph node unless the caller supplies an explicit cap."""

    return _fetch_all(
        client.graph.node.list,
        graph_id,
        item_name="nodes",
        page_size=page_size,
        max_items=max_items,
        max_retries=max_retries,
        retry_delay=retry_delay,
    )


def fetch_all_edges(
    client: Zep,
    graph_id: str,
    page_size: int = _DEFAULT_PAGE_SIZE,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    retry_delay: float = _DEFAULT_RETRY_DELAY,
    max_items: int | None = None,
) -> list[Any]:
    """Fetch every graph edge unless the caller supplies an explicit cap."""

    return _fetch_all(
        client.graph.edge.list,
        graph_id,
        item_name="edges",
        page_size=page_size,
        max_items=max_items,
        max_retries=max_retries,
        retry_delay=retry_delay,
    )
