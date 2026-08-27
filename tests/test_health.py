from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["app"] == "finance-tracker"


def test_dashboard_valid_range():
    response = client.get("/dashboard/monthly")
    assert response.status_code == 200
    assert response.json()["range_type"] == "monthly"


def test_dashboard_invalid_range():
    response = client.get("/dashboard/decade")
    assert response.status_code == 400
    assert "error" in response.json()["detail"]
