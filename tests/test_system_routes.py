from aoa.constants import API_VERSION


def test_root_endpoint(client):
    response = client.get("/")
    data = response.json()

    assert response.status_code == 200
    assert data["success"] is True
    assert data["version"] == API_VERSION
    assert data["docs"] == "/docs"


def test_health_and_status(client):
    health = client.get("/health").json()
    status = client.get("/api/v1/status").json()

    assert health["success"] is True
    assert health["status"] == "healthy"
    assert status["success"] is True
    assert status["status"] == "online"
    assert status["version"] == API_VERSION
