from __future__ import annotations

import os

import pytest

os.environ.setdefault("FIXTURES", "1")
os.environ["DATABASE_URL"] = ""

from eve_miro.api.state import reset_state  # noqa: E402


@pytest.fixture(autouse=True)
def _reset():
    reset_state()
    yield
    reset_state()
