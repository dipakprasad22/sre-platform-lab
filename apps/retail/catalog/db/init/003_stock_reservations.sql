-- One row per order. The order_id is the idempotency key for stock changes.
CREATE TABLE IF NOT EXISTS stock_reservations (
    order_id    TEXT        PRIMARY KEY,
    items       JSONB       NOT NULL,
    status      TEXT        NOT NULL CHECK (status IN ('reserved', 'released', 'committed')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
