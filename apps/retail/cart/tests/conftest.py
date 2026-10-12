import os

# Real tests use a local Redis on the default port (started by docker compose).
os.environ.setdefault("CART_REDIS_URL", "redis://localhost:6379/15")