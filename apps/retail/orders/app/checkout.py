"""The checkout flow from the design doc (section 5).

1. Read the cart.
2. Save the order as PENDING (this is our record that checkout started).
3. Reserve stock in catalog (idempotent by order_id).
4. Save the items and total.
5. Charge payment (idempotent by order_id) with timeout and retries.
6. PAID: commit stock, clear cart.  Failed: release stock.
   Unknown (timeout): leave PENDING. The reconcile job finds the true answer later.
"""

import logging
import uuid

import httpx
import psycopg
from psycopg_pool import ConnectionPool

from app.clients import CallFailed, call
from app.config import settings

log = logging.getLogger("orders.checkout")


class CheckoutError(Exception):
    """Checkout stopped. Carries the HTTP status and the order (if one was created)."""

    def __init__(self, status: int, detail: str, order: dict | None = None):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.order = order


# ---------- database helpers ----------


def load_order(pool: ConnectionPool, order_id: str) -> dict | None:
    with pool.connection() as conn:
        order = conn.execute(
            "SELECT id, user_id, status, total_paise, payment_id, failure_reason, "
            "created_at, updated_at FROM orders WHERE id = %s",
            (order_id,),
        ).fetchone()
        if order is None:
            return None
        order["items"] = conn.execute(
            "SELECT product_id, name, quantity, price_paise FROM order_items "
            "WHERE order_id = %s ORDER BY product_id",
            (order_id,),
        ).fetchall()
    return order


def find_by_key(pool: ConnectionPool, user_id: str, key: str) -> dict | None:
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT id FROM orders WHERE user_id = %s AND idempotency_key = %s",
            (user_id, key),
        ).fetchone()
    return load_order(pool, row["id"]) if row else None


def set_status(
    pool: ConnectionPool,
    order_id: str,
    status: str,
    reason: str | None = None,
    payment_id: str | None = None,
) -> dict:
    with pool.connection() as conn:
        conn.execute(
            "UPDATE orders SET status = %s, failure_reason = %s, "
            "payment_id = COALESCE(%s, payment_id), updated_at = now() WHERE id = %s",
            (status, reason, payment_id, order_id),
        )
    log.info("order=%s status=%s reason=%s", order_id, status, reason)
    return load_order(pool, order_id)


# ---------- calls to other services ----------


def release_stock(http: httpx.Client, order_id: str) -> None:
    """Best effort. If it fails, the reconcile job tries again later."""
    try:
        resp = call(
            http,
            "POST",
            f"{settings.catalog_url}/internal/reservations/{order_id}/release",
        )
        if resp.status_code not in (200, 404):
            log.error("release for order=%s returned %s", order_id, resp.status_code)
    except CallFailed as exc:
        log.error("could not release stock for order=%s: %s", order_id, exc)


def finish_payment(
    pool: ConnectionPool, http: httpx.Client, order: dict, resp: httpx.Response
):
    """Apply a payment answer to the order. Returns (http_status, order)."""
    order_id = order["id"]
    if resp.status_code != 200:
        # 4xx from the gateway means our request was wrong. No money moved.
        release_stock(http, order_id)
        return 502, set_status(
            pool,
            order_id,
            "PAYMENT_FAILED",
            f"payment rejected: HTTP {resp.status_code}",
        )

    payment = resp.json()
    if payment["status"] == "declined":
        release_stock(http, order_id)
        return 402, set_status(pool, order_id, "PAYMENT_FAILED", "card declined")

    # Paid. Commit the stock and clear the cart. These are "nice to have" steps:
    # the customer has paid, so the order is PAID even if they fail.
    try:
        call(
            http,
            "POST",
            f"{settings.catalog_url}/internal/reservations/{order_id}/commit",
        )
    except CallFailed as exc:
        log.error("could not commit stock for order=%s: %s", order_id, exc)
    try:
        call(
            http,
            "DELETE",
            f"{settings.cart_url}/api/cart",
            headers={"X-User-Id": order["user_id"]},
        )
    except CallFailed as exc:
        log.warning("could not clear cart for user=%s: %s", order["user_id"], exc)

    return 201, set_status(pool, order_id, "PAID", None, payment["payment_id"])


def leave_pending(pool: ConnectionPool, order_id: str, why: str):
    """We do not know if the customer was charged. Do NOT fail the order and do
    NOT release stock. The reconcile job asks again with the same idempotency
    key and gets the real answer."""
    log.error("payment result unknown for order=%s: %s", order_id, why)
    with pool.connection() as conn:
        conn.execute(
            "UPDATE orders SET failure_reason = %s, updated_at = now() WHERE id = %s",
            ("payment result unknown, will reconcile", order_id),
        )
    return 202, load_order(pool, order_id)


def charge(pool: ConnectionPool, http: httpx.Client, order: dict):
    """Ask the gateway to charge. Returns (http_status, order)."""
    order_id = order["id"]
    try:
        resp = call(
            http,
            "POST",
            f"{settings.payment_url}/payments",
            json={"order_id": order_id, "amount_paise": order["total_paise"]},
            headers={"Idempotency-Key": order_id},
        )
    except CallFailed as exc:
        if exc.ambiguous:
            return leave_pending(pool, order_id, str(exc))
        # Definitely not charged (could not connect, or gateway said 503).
        release_stock(http, order_id)
        return 503, set_status(
            pool, order_id, "PAYMENT_FAILED", "payment service unavailable"
        )
    if resp.status_code == 409:
        # An earlier attempt with this key is still running at the gateway.
        return leave_pending(
            pool, order_id, "earlier payment attempt still in progress"
        )
    return finish_payment(pool, http, order, resp)


# ---------- the main flow ----------


def place_order(pool: ConnectionPool, http: httpx.Client, user_id: str, key: str):
    """Returns (http_status, order). Raises CheckoutError when it stops early."""
    # 0. Same user + same key seen before: return that order (double click, client retry).
    existing = find_by_key(pool, user_id, key)
    if existing:
        return 200, existing

    # 1. Read the cart.
    try:
        cart_resp = call(
            http, "GET", f"{settings.cart_url}/api/cart", headers={"X-User-Id": user_id}
        )
    except CallFailed as exc:
        raise CheckoutError(503, "cart service unavailable") from exc
    items = cart_resp.json().get("items", []) if cart_resp.status_code == 200 else []
    if not items:
        raise CheckoutError(400, "cart is empty")

    # 2. Save the order as PENDING.
    order_id = f"ord_{uuid.uuid4().hex[:20]}"
    try:
        with pool.connection() as conn:
            conn.execute(
                "INSERT INTO orders (id, user_id, idempotency_key, status) "
                "VALUES (%s, %s, %s, 'PENDING')",
                (order_id, user_id, key),
            )
    except psycopg.errors.UniqueViolation:
        # A parallel request with the same key got there first.
        return 200, find_by_key(pool, user_id, key)
    log.info("order=%s created for user=%s", order_id, user_id)

    # 3. Reserve stock (also gives us the current prices).
    try:
        resp = call(
            http,
            "POST",
            f"{settings.catalog_url}/internal/reservations",
            json={"order_id": order_id, "items": items},
        )
    except CallFailed as exc:
        release_stock(http, order_id)  # in case it was reserved but the answer was lost
        order = set_status(pool, order_id, "CANCELLED", "catalog unavailable")
        raise CheckoutError(503, "catalog service unavailable", order) from exc
    if resp.status_code != 200:
        detail = resp.json().get("detail", f"HTTP {resp.status_code}")
        order = set_status(pool, order_id, "CANCELLED", str(detail))
        raise CheckoutError(409, str(detail), order)
    reservation = resp.json()

    # 4. Save items and total in one transaction.
    with pool.connection() as conn, conn.transaction():
        for item in reservation["items"]:
            conn.execute(
                "INSERT INTO order_items (order_id, product_id, name, quantity, price_paise) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    order_id,
                    item["product_id"],
                    item["name"],
                    item["quantity"],
                    item["price_paise"],
                ),
            )
        conn.execute(
            "UPDATE orders SET total_paise = %s, updated_at = now() WHERE id = %s",
            (reservation["total_paise"], order_id),
        )

    # 5 and 6. Charge and apply the result.
    return charge(pool, http, load_order(pool, order_id))


def reconcile(
    pool: ConnectionPool, http: httpx.Client, older_than_seconds: int
) -> dict:
    """Fix orders stuck in PENDING (crash, or unknown payment result)."""
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT id FROM orders WHERE status = 'PENDING' "
            "AND created_at < now() - make_interval(secs => %s) ORDER BY created_at LIMIT 100",
            (older_than_seconds,),
        ).fetchall()

    summary = {
        "checked": len(rows),
        "paid": 0,
        "failed": 0,
        "cancelled": 0,
        "still_pending": 0,
    }
    for row in rows:
        order = load_order(pool, row["id"])
        if order["total_paise"] == 0:
            # Checkout stopped before the items were saved. Give back any stock.
            release_stock(http, order["id"])
            set_status(pool, order["id"], "CANCELLED", "checkout did not finish")
            summary["cancelled"] += 1
            continue
        # Ask the gateway again with the SAME key: it returns the real result,
        # or charges now if the first request never arrived. Never twice.
        _, updated = charge(pool, http, order)
        key = {"PAID": "paid", "PAYMENT_FAILED": "failed"}.get(
            updated["status"], "still_pending"
        )
        summary[key] += 1
    log.info("reconcile finished: %s", summary)
    return summary
