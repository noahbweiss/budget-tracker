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
    assert response.headers["content-type"].startswith("text/html")
    assert "Finance Tracker" in response.text


def test_static_files_served():
    response = client.get("/static/css/style.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]


def test_dashboard_valid_range():
    response = client.get("/dashboard/monthly")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<!doctype html>" in response.text.lower()
    assert "range-switcher" in response.text


def test_dashboard_invalid_range():
    response = client.get("/dashboard/decade")
    assert response.status_code == 400
    assert "error" in response.json()["detail"]


def test_dashboard_htmx_request_returns_fragment_only():
    """An HTMX-triggered range switch should get just the swappable
    fragment, not a full page — see dashboard.py's HX-Request check.
    """
    response = client.get("/dashboard/weekly", headers={"HX-Request": "true"})
    assert response.status_code == 200
    assert "<!doctype html>" not in response.text.lower()
    assert "range-switcher" in response.text


def test_dashboard_daily_has_no_chart():
    response = client.get("/dashboard/daily")
    assert response.status_code == 200
    assert 'id="dashboard-chart"' not in response.text


def test_dashboard_offset_navigates_periods():
    current = client.get("/dashboard/monthly")
    previous = client.get("/dashboard/monthly?offset=1")
    assert current.status_code == previous.status_code == 200
    assert "period-nav__today" not in current.text  # already viewing the current period
    assert "period-nav__today" in previous.text  # viewing a past period — offers a way back
