import os

import pytest  # type: ignore[import-not-found]

try:
    from redis import Redis  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - fallback for environments without redis installed
    Redis = None  # type: ignore[assignment]

try:
    from starlette.testclient import TestClient  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - fallback for environments without starlette installed
    from fastapi.testclient import TestClient  # type: ignore[import-not-found]

from app.main import app


def redis_available() -> bool:
    try:
        return Redis.from_url(os.environ["CART_REDIS_URL"], socket_timeout=0.5).ping()
    except Exception:
        return False


needs_redis = pytest.mark.skipif(not redis_available(), reason="Redis not running")
USER = {"X-User-Id": "test-user"}


def test_healthz_works_without_redis():
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200


@needs_redis
def test_add_update_and_remove_items():
    with TestClient(app) as client:
        client.delete("/api/cart", headers=USER)
        client.post(
            "/api/cart/items", json={"product_id": 2, "quantity": 1}, headers=USER
        )
        r = client.post(
            "/api/cart/items", json={"product_id": 2, "quantity": 2}, headers=USER
        )
        assert r.json()["items"] == [{"product_id": 2, "quantity": 3}]

        r = client.patch("/api/cart/items/2", json={"quantity": 0}, headers=USER)
        assert r.json()["items"] == []


@needs_redis
def test_cart_has_an_expiry():
    with TestClient(app) as client:
        client.post(
            "/api/cart/items", json={"product_id": 1, "quantity": 1}, headers=USER
        )
    ttl = Redis.from_url(os.environ["CART_REDIS_URL"]).ttl("cart:test-user")
    assert 0 < ttl <= 7 * 24 * 3600


@needs_redis
def test_quantity_is_capped():
    with TestClient(app) as client:
        client.delete("/api/cart", headers=USER)
        for _ in range(3):
            r = client.post(
                "/api/cart/items", json={"product_id": 5, "quantity": 5}, headers=USER
            )
        assert r.json()["items"] == [{"product_id": 5, "quantity": 10}]


def test_missing_user_header_is_rejected():
    with TestClient(app) as client:
        assert client.get("/api/cart").status_code == 422