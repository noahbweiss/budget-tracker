from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_plan_page_loads():
    response = client.get("/plan/")
    assert response.status_code == 200
    assert "Coming soon" in response.text


def test_plan_nav_link_present_on_other_pages():
    response = client.get("/")
    assert response.status_code == 200
    assert 'href="/plan/"' in response.text
