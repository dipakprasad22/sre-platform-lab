import logging
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Request, Response  # type: ignore[import-not-found]
from fastapi.responses import JSONResponse  # type: ignore[import-not-found]
from pydantic import BaseModel, Field  # type: ignore[import-not-found]
from redis import Redis  # type: ignore[import-not-found]
from redis.exceptions import ConnectionError as RedisConnectionError  # type: ignore[import-not-found]
from redis.exceptions import TimeoutError as RedisTimeoutError  # type: ignore[import-not-found]

from app.config import settings

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
log = logging.getLogger("cart")

TTL_SECONDS = settings.cart_ttl_days * 24 * 3600


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The client keeps a small pool of connections. Short timeouts so a slow
    # Redis cannot make every request hang.
    app.state.redis = Redis.from_url(
        settings.redis_url,
        socket_timeout=settings.redis_timeout_seconds,
        socket_connect_timeout=settings.redis_timeout_seconds,
        decode_responses=True,
    )
    log.info("cart started")
    yield
    app.state.redis.close()
    log.info("cart stopped")


app = FastAPI(title="cart", version="0.1.0", lifespan=lifespan)


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


Db = Annotated[Redis, Depends(get_redis)]
UserId = Annotated[str, Header(alias="X-User-Id", min_length=1, max_length=64)]


@app.exception_handler(RedisConnectionError)
@app.exception_handler(RedisTimeoutError)
def redis_unavailable(request: Request, exc: Exception):
    log.error("redis unavailable on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=503, content={"detail": "service temporarily unavailable"}
    )


class CartItem(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=settings.max_quantity_per_item)


class QuantityUpdate(BaseModel):
    quantity: int = Field(ge=0, le=settings.max_quantity_per_item)


class Cart(BaseModel):
    user_id: str
    items: list[CartItem]


def cart_key(user_id: str) -> str:
    return f"cart:{user_id}"


def read_cart(db: Redis, user_id: str) -> Cart:
    raw = db.hgetall(cart_key(user_id))  # {"product_id": "quantity", ...}
    items = [
        CartItem(product_id=int(pid), quantity=int(qty))
        for pid, qty in sorted(raw.items(), key=lambda kv: int(kv[0]))
    ]
    return Cart(user_id=user_id, items=items)


@app.get("/healthz")
def healthz():
    """Liveness: never checks Redis."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz(response: Response, db: Db):
    try:
        db.ping()
        return {"status": "ready"}
    except (RedisConnectionError, RedisTimeoutError) as exc:
        log.warning("readiness check failed: %s", exc)
        response.status_code = 503
        return {"status": "not ready", "reason": "redis unavailable"}


@app.get("/api/cart", response_model=Cart)
def get_cart(user_id: UserId, db: Db):
    return read_cart(db, user_id)


@app.post("/api/cart/items", response_model=Cart)
def add_item(item: CartItem, user_id: UserId, db: Db):
    key = cart_key(user_id)
    # MULTI/EXEC: both commands run together, so the cart never exists without an expiry.
    pipe = db.pipeline(transaction=True)
    pipe.hincrby(key, str(item.product_id), item.quantity)
    pipe.expire(key, TTL_SECONDS)
    new_qty, _ = pipe.execute()
    if new_qty > settings.max_quantity_per_item:
        db.hset(key, str(item.product_id), settings.max_quantity_per_item)
    return read_cart(db, user_id)


@app.patch("/api/cart/items/{product_id}", response_model=Cart)
def update_item(product_id: int, update: QuantityUpdate, user_id: UserId, db: Db):
    key = cart_key(user_id)
    pipe = db.pipeline(transaction=True)
    if update.quantity == 0:
        pipe.hdel(key, str(product_id))
    else:
        pipe.hset(key, str(product_id), update.quantity)
    pipe.expire(key, TTL_SECONDS)
    pipe.execute()
    return read_cart(db, user_id)


@app.delete("/api/cart/items/{product_id}", response_model=Cart)
def remove_item(product_id: int, user_id: UserId, db: Db):
    db.hdel(cart_key(user_id), str(product_id))
    return read_cart(db, user_id)


@app.delete("/api/cart", status_code=204)
def clear_cart(user_id: UserId, db: Db):
    """Called by the orders service after a successful payment."""
    db.delete(cart_key(user_id))