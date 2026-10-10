from pydantic_settings import BaseSettings, SettingsConfigDict  # pyright: ignore[reportMissingImports]


class Settings(BaseSettings):
    """App settings, read from environment variables that start with CATALOG_."""

    model_config = SettingsConfigDict(env_prefix="CATALOG_")

    # No default on purpose: the app should fail fast if the database is not configured.
    database_url: str
    db_pool_min: int = 1
    db_pool_max: int = 10
    db_timeout_seconds: float = 2.0


settings = Settings()
