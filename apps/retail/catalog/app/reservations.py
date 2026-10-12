"""Stock reservations, called only by the orders service (never by users).

Every operation is idempotent: calling it again with the same order_id gives the
same result and never changes stock twice. This makes retries safe.
"""

import logging
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field, model_validator

from app.db import get_pool

log = logging.getLogger("catalog.reservations")
router = APIRouter(prefix="/internal/reservations")
Pool = Annotated[ConnectionPool, Depends(get_pool)]


class ReserveItem(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=100)


class ReserveRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=64)
    items: list[ReserveItem] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def no_duplicate_products(self):
        ids = [i.product_id for i in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("each product may appear only once")
        return self


class ReservedItem(BaseModel):
    product_id: int
    name: str
    quantity: int
    price_paise: int


class Reservation(BaseModel):
    order_id: str
    status: str
    items: list[ReservedItem]
    total_paise: int


def to_reservation(order_id: str, status: str, items: list[dict]) -> Reservation:
    total = sum(i["price_paise"] * i["quantity"] for i in items)
    return Reservation(order_id=order_id, status=status, items=items, total_paise=total)


@router.post("", response_model=Reservation)
def reserve(req: ReserveRequest, pool: Pool):
    try:
        with pool.connection() as conn, conn.transaction():
            # 1. Seen this order before? Return the saved result (idempotent replay).
            existing = conn.execute(
                "SELECT status, items FROM stock_reservations WHERE order_id = %s FOR UPDATE",
                (req.order_id,),
            ).fetchone()
            if existing:
                if existing["status"] == "released":
                    raise HTTPException(409, "reservation was already released")
                return to_reservation(
                    req.order_id, existing["status"], existing["items"]
                )

            # 2. Take stock for each item. Always lock rows in the same order
            #    (by product_id) so two orders can never deadlock each other.
            reserved = []
            for item in sorted(req.items, key=lambda i: i.product_id):
                row = conn.execute(
                    "UPDATE products SET stock = stock - %s, updated_at = now() "
                    "WHERE id = %s AND stock >= %s "
                    "RETURNING id, name, price_paise",
                    (item.quantity, item.product_id, item.quantity),
                ).fetchone()
                if row is None:
                    found = conn.execute(
                        "SELECT 1 FROM products WHERE id = %s", (item.product_id,)
                    ).fetchone()
                    # Raising inside the transaction rolls back ALL stock changes above.
                    if found is None:
                        raise HTTPException(404, f"product {item.product_id} not found")
                    raise HTTPException(
                        409, f"not enough stock for product {item.product_id}"
                    )
                reserved.append(
                    {
                        "product_id": row["id"],
                        "name": row["name"],
                        "quantity": item.quantity,
                        "price_paise": row["price_paise"],
                    }
                )

            # 3. Save the reservation. The PRIMARY KEY stops two parallel requests
            #    for the same order from both succeeding.
            conn.execute(
                "INSERT INTO stock_reservations (order_id, items, status) "
                "VALUES (%s, %s, 'reserved')",
                (req.order_id, Jsonb(reserved)),
            )
            log.info(
                "reserved stock for order=%s items=%d", req.order_id, len(reserved)
            )
            return to_reservation(req.order_id, "reserved", reserved)
    except psycopg.errors.UniqueViolation:
        # A parallel request for the same order won. Our changes were rolled back.
        with pool.connection() as conn:
            row = conn.execute(
                "SELECT status, items FROM stock_reservations WHERE order_id = %s",
                (req.order_id,),
            ).fetchone()
        return to_reservation(req.order_id, row["status"], row["items"])


@router.post("/{order_id}/release", response_model=Reservation)
def release(order_id: str, pool: Pool):
    """Give the stock back (payment failed or order cancelled)."""
    with pool.connection() as conn, conn.transaction():
        row = conn.execute(
            "SELECT status, items FROM stock_reservations WHERE order_id = %s FOR UPDATE",
            (order_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "reservation not found")
        if row["status"] == "committed":
            raise HTTPException(409, "reservation is already committed")
        if row["status"] == "reserved":
            for item in sorted(row["items"], key=lambda i: i["product_id"]):
                conn.execute(
                    "UPDATE products SET stock = stock + %s, updated_at = now() WHERE id = %s",
                    (item["quantity"], item["product_id"]),
                )
            conn.execute(
                "UPDATE stock_reservations SET status = 'released', updated_at = now() "
                "WHERE order_id = %s",
                (order_id,),
            )
            log.info("released stock for order=%s", order_id)
        return to_reservation(order_id, "released", row["items"])


@router.post("/{order_id}/commit", response_model=Reservation)
def commit(order_id: str, pool: Pool):
    """Make the reservation final (payment succeeded)."""
    with pool.connection() as conn, conn.transaction():
        row = conn.execute(
            "SELECT status, items FROM stock_reservations WHERE order_id = %s FOR UPDATE",
            (order_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "reservation not found")
        if row["status"] == "released":
            raise HTTPException(409, "reservation was already released")
        if row["status"] == "reserved":
            conn.execute(
                "UPDATE stock_reservations SET status = 'committed', updated_at = now() "
                "WHERE order_id = %s",
                (order_id,),
            )
            log.info("committed stock for order=%s", order_id)
        return to_reservation(order_id, "committed", row["items"])
