import os

os.environ.setdefault("ORDERS_DATABASE_URL", "postgresql://test:test@127.0.0.1:1/test")
os.environ.setdefault("ORDERS_DB_TIMEOUT_SECONDS", "0.5")
os.environ.setdefault("ORDERS_CATALOG_URL", "http://127.0.0.1:1")
os.environ.setdefault("ORDERS_CART_URL", "http://127.0.0.1:1")
os.environ.setdefault("ORDERS_PAYMENT_URL", "http://127.0.0.1:1")
