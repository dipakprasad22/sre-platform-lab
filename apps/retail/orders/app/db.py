from fastapi import Request
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import settings


def create_pool() -> ConnectionPool:
    return ConnectionPool(
        conninfo=settings.database_url,
        min_size=settings.db_pool_min,
        max_size=settings.db_pool_max,
        timeout=settings.db_timeout_seconds,
        kwargs={"row_factory": dict_row},
        open=False,
    )


def get_pool(request: Request) -> ConnectionPool:
    return request.app.state.pool
