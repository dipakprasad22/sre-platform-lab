CREATE TABLE IF NOT EXISTS products (
    id           BIGSERIAL PRIMARY KEY,
    name         TEXT        NOT NULL,
    description  TEXT        NOT NULL DEFAULT '',
    price_paise  BIGINT      NOT NULL CHECK (price_paise >= 0),
    stock        INTEGER     NOT NULL CHECK (stock >= 0),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);