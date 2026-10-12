CREATE TABLE IF NOT EXISTS orders (
    id               TEXT        PRIMARY KEY,
    user_id          TEXT        NOT NULL,
    idempotency_key  TEXT        NOT NULL,
    status           TEXT        NOT NULL
        CHECK (status IN ('PENDING', 'PAID', 'PAYMENT_FAILED', 'CANCELLED')),
    total_paise      BIGINT      NOT NULL DEFAULT 0 CHECK (total_paise >= 0),
    payment_id       TEXT,
    failure_reason   TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- The same user pressing "Place order" twice with the same key gets one order.
    UNIQUE (user_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS order_items (
    order_id     TEXT    NOT NULL REFERENCES orders (id),
    product_id   BIGINT  NOT NULL,
    name         TEXT    NOT NULL,
    quantity     INTEGER NOT NULL CHECK (quantity > 0),
    price_paise  BIGINT  NOT NULL CHECK (price_paise >= 0),
    PRIMARY KEY (order_id, product_id)
);

-- "My orders" page: newest first for one user.
CREATE INDEX IF NOT EXISTS orders_user_created_idx ON orders (user_id, created_at DESC);
-- Reconcile job: find stuck PENDING orders quickly.
CREATE INDEX IF NOT EXISTS orders_pending_idx ON orders (created_at) WHERE status = 'PENDING';
