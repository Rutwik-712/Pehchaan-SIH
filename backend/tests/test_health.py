from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["service"] == "Criminal Network Analysis System"
    assert payload["version"] == "0.8.0-phase8"
    assert response.headers["X-Request-ID"]


def test_root_points_to_health_and_docs() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["health"] == "/api/v1/health"
    assert response.json()["docs"] == "/docs"
