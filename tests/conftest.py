from __future__ import annotations

import os

import pytest

os.environ.setdefault("FIXTURES", "1")
os.environ["DATABASE_URL"] = ""
# Keep the existing offline suite on stubs. Production/API default is in-tree.
os.environ["EVE_MIRO_ENGINES"] = "stub"
os.environ.setdefault("MIROFISH_TIMEOUT_S", "120")

from eve_miro.api.state import reset_state  # noqa: E402


@pytest.fixture(autouse=True)
def _reset():
    reset_state()
    yield
    reset_state()
