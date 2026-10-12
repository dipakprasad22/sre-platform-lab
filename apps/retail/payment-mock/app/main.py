import asyncio
import logging
import random
import uuid

# pyright: reportMissingImports=false
try:
    from pydantic import BaseModel, Field
except ImportError:  # pragma: no cover
    from pydantic.v1 import BaseModel, Field

from fastapi import FastAPI, Header, HTTPException

from app.config import settings

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
log = logging.getLogger("payment-mock")

app = FastAPI(title="payment-mock", version="0.1.0")


class Chaos(BaseModel):
    failure_rate: float = Field(ge=0, le=1)
    decline_rate: float = Field(ge=0, le=1)
    latency_ms: int = Field(ge=0, le=30_000)


# Current chaos settings. Can be changed at runtime through /admin/chaos.
chaos = Chaos(
    failure_rate=settings.failure_rate,
    decline_rate=settings.decline_rate,
    latency_ms=settings.latency_ms,
)

# Idempotency store: Idempotency-Key -> (request, response).
# Known limitation: kept in memory, so it only works with ONE replica and is lost
# on restart. Real payment gateways keep this in a database.
_results: dict[str, tuple[dict, dict]] = {}


class PaymentRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=64)
    amount_paise: int = Field(gt=0)


class PaymentResult(BaseModel):
    payment_id: str
    order_id: str
    amount_paise: int
    status: str  # "succeeded" or "declined"


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    return {"status": "ready"}


@app.get("/admin/chaos", response_model=Chaos)
def get_chaos():
    return chaos


@app.put("/admin/chaos", response_model=Chaos)
def set_chaos(new: Chaos):
    """Change failure settings without a redeploy. Internal use only, never expose publicly."""
    global chaos
    chaos = new
    log.warning("chaos settings changed: %s", chaos.model_dump())
    return chaos


@app.post("/payments", response_model=PaymentResult)
async def create_payment(
    req: PaymentRequest,
    idempotency_key: str = Header(min_length=1, max_length=128),
):
    # 1. Same key seen before: return the saved answer, never charge twice.
    if idempotency_key in _results:
        saved_req, saved_resp = _results[idempotency_key]
        if saved_req != req.model_dump():
            # Same key but different details is a client bug. Refuse it.
            raise HTTPException(
                status_code=422,
                detail="idempotency key already used with different details",
            )
        log.info("replay for key=%s order=%s", idempotency_key, req.order_id)
        return saved_resp

    # 2. Simulate a slow gateway.
    if chaos.latency_ms:
        await asyncio.sleep(chaos.latency_ms / 1000)

    # 3. Simulate an outage. Nothing is saved, so a retry can still succeed.
    if random.random() < chaos.failure_rate:
        log.error("simulated outage for order=%s", req.order_id)
        raise HTTPException(status_code=503, detail="payment gateway unavailable")

    # 4. Normal result: the bank approves or declines.
    status = "declined" if random.random() < chaos.decline_rate else "succeeded"
    resp = PaymentResult(
        payment_id=f"pay_{uuid.uuid4().hex[:16]}",
        order_id=req.order_id,
        amount_paise=req.amount_paise,
        status=status,
    ).model_dump()
    _results[idempotency_key] = (req.model_dump(), resp)
    log.info("payment %s order=%s status=%s", resp["payment_id"], req.order_id, status)
    return resp