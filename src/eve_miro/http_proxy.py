"""Proxy-env hardening shared by all live HTTP clients.

Some environments ship a ``no_proxy``/``NO_PROXY`` list containing bracketed
IPv6 literals (e.g. ``"[::1]"``). httpx parses those entries as host:port and
raises ``InvalidURL("Invalid port: ':1]'")`` at client construction, which
fails every live fetch (and broke
``tests/test_adapters.py::test_mirofish_run_raises_when_server_down`` in
environments with such a list). Brackets are unnecessary for httpx's
plain-host no_proxy matching, so we drop bracketed entries for the
duration of client construction and restore the environment afterwards.
"""

from __future__ import annotations

import contextlib
import os
from typing import Iterator

_PROXY_HOST_VARS = ("no_proxy", "NO_PROXY")


def clean_no_proxy(value: str) -> str:
    """Drop bracketed-IPv6 entries httpx cannot parse."""
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return ",".join(p for p in parts if not (p.startswith("[") and p.endswith("]")))


@contextlib.contextmanager
def sanitized_proxy_env() -> Iterator[None]:
    """Temporarily drop bracketed-IPv6 no_proxy entries httpx cannot parse."""
    saved: dict[str, str] = {}
    for var in _PROXY_HOST_VARS:
        val = os.environ.get(var)
        if val is None:
            continue
        cleaned = clean_no_proxy(val)
        if cleaned != val:
            saved[var] = val
            os.environ[var] = cleaned
    try:
        yield
    finally:
        for var, val in saved.items():
            os.environ[var] = val
