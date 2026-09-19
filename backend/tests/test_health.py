from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check():
    """Verify that GET /health returns 200 and healthy status."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_root():
    """Verify that root endpoint responds."""
    response = client.get("/")
    assert response.status_code == 200
    assert "message" in response.json()
