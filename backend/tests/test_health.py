from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_ok():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "verified-call"


def test_health_leaks_no_secrets():
    """Standing rule 5: no credential may appear in a response payload."""
    with TestClient(app) as client:
        body = client.get("/health").text.lower()
    for forbidden in ("api_key", "apikey", "secret", "password", "token"):
        assert forbidden not in body, f"/health exposed {forbidden!r}: {body}"
