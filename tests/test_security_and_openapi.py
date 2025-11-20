"""Security and OpenAPI metadata regression tests."""
from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_cedh_routes_require_authentication() -> None:
    response = client.get("/api/v1/cedh/search")
    assert response.status_code == 403
    payload = response.json().get("error", {})
    assert payload.get("message") == "Not authenticated"


def test_openapi_marks_cedh_routes_secure() -> None:
    schema = app.openapi()
    cedh_search = schema["paths"]["/api/v1/cedh/search"]["get"]
    assert {"HTTPBearer": []} in cedh_search.get("security", [])


def test_openapi_limits_operations() -> None:
    schema = app.openapi()
    operation_count = sum(len(methods) for methods in schema["paths"].values())
    assert operation_count <= 30
    assert "/api/v1/cedh/search" in schema["paths"]
