from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_settings_page_loads():
    response = client.get("/settings/")
    assert response.status_code == 200
    assert "Coming soon" in response.text


def test_settings_button_present_on_other_pages():
    response = client.get("/")
    assert response.status_code == 200
    assert 'href="/settings/"' in response.text
