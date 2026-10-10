import os

# Point tests at a port where nothing is listening, so no real database is needed.
os.environ.setdefault("CATALOG_DATABASE_URL", "postgresql://test:test@127.0.0.1:1/test")
os.environ.setdefault("CATALOG_DB_TIMEOUT_SECONDS", "0.5")
