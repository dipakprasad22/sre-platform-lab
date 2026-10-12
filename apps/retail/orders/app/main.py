import logging
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from psycopg_pool import ConnectionPool, PoolTimeout

from app import checkout
from app.config import settings
from app.db import create_pool, get_pool

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
log = logging.getLogger("orders")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = create_pool()
    app.state.pool.open(wait=False)
    # One shared HTTP client: reuses connections to other services.
    app.state.http = httpx.Client(limits=httpx.Limits(max_connections=50))
    log.info("orders started")
    yield
    app.state.http.close()
    app.state.pool.close()
    log.info("orders stopped")


app = FastAPI(title="orders", version="0.1.0", lifespan=lifespan)


def get_http(request: Request) -> httpx.Client:
    return request.app.state.http


Pool = Annotated[ConnectionPool, Depends(get_pool)]
Http = Annotated[httpx.Client, Depends(get_http)]
UserId = Annotated[str, Header(alias="X-User-Id", min_length=1, max_length=64)]


@app.exception_handler(PoolTimeout)
@app.exception_handler(psycopg.OperationalError)
def database_unavailable(request: Request, exc: Exception):
    log.error("database unavailable on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=503, content={"detail": "service temporarily unavailable"}
    )


@app.exception_handler(checkout.CheckoutError)
def checkout_stopped(request: Request, exc: checkout.CheckoutError):
    return JSONResponse(
        status_code=exc.status,
        content={"detail": exc.detail, "order": jsonable(exc.order)},
    )


def jsonable(order: dict | None):
    if order is None:
        return None
    return {
        k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in order.items()
    }


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/readyz")
def readyz(response: Response, pool: Pool):
    """Checks only OUR database. Never other services: if payment is down,
    orders must stay in the load balancer to return clear errors and serve order history."""
    try:
        with pool.connection(timeout=settings.db_timeout_seconds) as conn:
            conn.execute("SELECT 1")
        return {"status": "ready"}
    except (PoolTimeout, psycopg.Error) as exc:
        log.warning("readiness check failed: %s", exc)
        response.status_code = 503
        return {"status": "not ready", "reason": "database unavailable"}


@app.post("/api/orders")
def place_order(
    user_id: UserId,
    pool: Pool,
    http: Http,
    idempotency_key: Annotated[str, Header(min_length=8, max_length=128)],
):
    """Checkout. The client sends a new Idempotency-Key for each new order attempt."""
    status, order = checkout.place_order(pool, http, user_id, idempotency_key)
    return JSONResponse(status_code=status, content=jsonable(order))


@app.get("/api/orders/{order_id}")
def get_order(order_id: str, user_id: UserId, pool: Pool):
    order = checkout.load_order(pool, order_id)
    # Same answer for "does not exist" and "belongs to someone else",
    # so nobody can guess other users' order IDs.
    if order is None or order["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="order not found")
    return jsonable(order)


@app.get("/api/orders")
def list_orders(
    user_id: UserId, pool: Pool, limit: int = Query(default=20, ge=1, le=100)
):
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT id, status, total_paise, created_at FROM orders "
            "WHERE user_id = %s ORDER BY created_at DESC LIMIT %s",
            (user_id, limit),
        ).fetchall()
    return [jsonable(r) for r in rows]


@app.post("/internal/orders/reconcile")
def run_reconcile(
    pool: Pool, http: Http, older_than_seconds: int = Query(default=60, ge=0)
):
    """Fix stuck PENDING orders. Later this runs as a Kubernetes CronJob."""
    return checkout.reconcile(pool, http, older_than_seconds)
