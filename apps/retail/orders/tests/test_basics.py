from fastapi.testclient import TestClient

from app.main import app


def test_healthz_works_without_dependencies():
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200


def test_checkout_needs_user_and_idempotency_key():
    with TestClient(app) as client:
        assert client.post("/api/orders").status_code == 422
        r = client.post("/api/orders", headers={"X-User-Id": "u1"})
        assert r.status_code == 422
