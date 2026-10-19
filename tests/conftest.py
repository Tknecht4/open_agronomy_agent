from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def loopback_test_client_default():
    """Exercise the real loopback guard; explicit hostile/LAN origins stay explicit."""
    original = TestClient.__init__
    def initialize(self, app, *args, **kwargs):
        if not args and "base_url" not in kwargs:
            kwargs["base_url"] = "http://127.0.0.1:8000"
        original(self, app, *args, **kwargs)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(TestClient, "__init__", initialize)
        yield
