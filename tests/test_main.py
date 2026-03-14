from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in {"ok", "degraded"}  # depends on whether Kafka is running
    assert data["version"] == settings.VERSION
    assert "services" in data
