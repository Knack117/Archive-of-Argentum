import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app


@pytest.fixture(scope="session")
def client():
    """Shared TestClient for FastAPI app."""
    return TestClient(app)
