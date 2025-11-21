import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app import MAX_OPENAPI_OPERATIONS, PRIORITIZED_OPENAPI_PATHS, app
from aoa.security import verify_api_key


def test_verify_api_key_accepts_default_and_rejects_invalid():
    valid_credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="test-key")
    assert verify_api_key(valid_credentials) == "test-key"

    invalid_credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong")
    with pytest.raises(HTTPException) as exc:
        verify_api_key(invalid_credentials)

    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid API key"


def test_openapi_limits_and_security_defaults():
    schema = app.openapi()

    assert len(schema["paths"]) <= MAX_OPENAPI_OPERATIONS

    cards_search = schema["paths"].get("/api/v1/cards/search", {}).get("post", {})
    assert cards_search.get("security") == [{"HTTPBearer": []}]

    root_path = schema["paths"].get("/", {}).get("get", {})
    assert root_path.get("security") is None

    for prioritized in PRIORITIZED_OPENAPI_PATHS:
        if prioritized in schema["paths"]:
            assert "security" in next(iter(schema["paths"][prioritized].values()))
