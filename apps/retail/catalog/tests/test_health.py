from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]

from app.main import app


def test_healthz_works_without_database():
    with TestClient(app) as client:
        r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readyz_fails_when_database_is_down():
    with TestClient(app) as client:
        r = client.get("/readyz")
    assert r.status_code == 503
    assert r.json()["status"] == "not ready"
