from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
NORMAL = {"failure_rate": 0, "decline_rate": 0, "latency_ms": 0}


def pay(key, order_id="o-1", amount=1000):
    return client.post(
        "/payments",
        json={"order_id": order_id, "amount_paise": amount},
        headers={"Idempotency-Key": key},
    )


def test_same_key_never_charges_twice():
    client.put("/admin/chaos", json=NORMAL)
    first = pay("key-1")
    second = pay("key-1")
    assert first.status_code == 200
    assert first.json()["status"] == "succeeded"
    assert second.json()["payment_id"] == first.json()["payment_id"]


def test_same_key_with_different_amount_is_rejected():
    client.put("/admin/chaos", json=NORMAL)
    pay("key-2", amount=1000)
    assert pay("key-2", amount=9999).status_code == 422


def test_outage_returns_503_and_retry_can_succeed():
    client.put("/admin/chaos", json={**NORMAL, "failure_rate": 1})
    assert pay("key-3").status_code == 503
    client.put("/admin/chaos", json=NORMAL)
    assert pay("key-3").status_code == 200


def test_decline_is_a_normal_answer():
    client.put("/admin/chaos", json={**NORMAL, "decline_rate": 1})
    r = pay("key-4")
    assert r.status_code == 200
    assert r.json()["status"] == "declined"


def test_missing_idempotency_key_is_rejected():
    r = client.post("/payments", json={"order_id": "o-9", "amount_paise": 100})
    assert r.status_code == 422


def test_parallel_requests_with_same_key_charge_only_once():
    import asyncio

    import httpx

    client.put("/admin/chaos", json={**NORMAL, "latency_ms": 300})

    async def two_at_once():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
            body = {"order_id": "o-par", "amount_paise": 500}
            headers = {"Idempotency-Key": "key-par"}
            return await asyncio.gather(
                ac.post("/payments", json=body, headers=headers),
                ac.post("/payments", json=body, headers=headers),
            )

    codes = sorted(r.status_code for r in asyncio.run(two_at_once()))
    client.put("/admin/chaos", json=NORMAL)
    assert codes == [200, 409]
