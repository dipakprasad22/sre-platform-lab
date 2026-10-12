import logging
from contextlib import asynccontextmanager
from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from psycopg_pool import ConnectionPool, PoolTimeout
from pydantic import BaseModel

from app.config import settings
from app.db import create_pool, get_pool
from app.reservations import router as reservations_router

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
log = logging.getLogger("catalog")

Pool = Annotated[ConnectionPool, Depends(get_pool)]


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = create_pool()
    # wait=False: start even if the database is down.
    # The pod stays alive and /readyz reports "not ready" until the database is back.
    app.state.pool.open(wait=False)
    log.info("catalog started")
    yield
    # Graceful shutdown: close database connections cleanly.
    app.state.pool.close()
    log.info("catalog stopped")


app = FastAPI(title="catalog", version="0.1.0", lifespan=lifespan)
app.include_router(reservations_router)


@app.exception_handler(PoolTimeout)
@app.exception_handler(psycopg.OperationalError)
def database_unavailable(request: Request, exc: Exception):
    """Return 503 (try again later) instead of a generic 500 when the database is down."""
    log.error("database unavailable on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=503, content={"detail": "service temporarily unavailable"}
    )


class Product(BaseModel):
    id: int
    name: str
    description: str
    price_paise: int
    stock: int


@app.get("/healthz")
def healthz():
    """Liveness: is the process running? Never checks the database."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz(response: Response, pool: Pool):
    """Readiness: can this instance serve real requests right now?"""
    try:
        with pool.connection(timeout=settings.db_timeout_seconds) as conn:
            conn.execute("SELECT 1")
        return {"status": "ready"}
    except (PoolTimeout, psycopg.Error) as exc:
        log.warning("readiness check failed: %s", exc)
        response.status_code = 503
        return {"status": "not ready", "reason": "database unavailable"}


@app.get("/api/products", response_model=list[Product])
def list_products(
    pool: Pool,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """List products, a page at a time. Never return the whole table."""
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT id, name, description, price_paise, stock "
            "FROM products ORDER BY id LIMIT %s OFFSET %s",
            (limit, offset),
        ).fetchall()
    return rows


@app.get("/api/products/{product_id}", response_model=Product)
def get_product(product_id: int, pool: Pool):
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT id, name, description, price_paise, stock FROM products WHERE id = %s",
            (product_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="product not found")
    return row
