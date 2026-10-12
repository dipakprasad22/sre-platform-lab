from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings, read from environment variables that start with CART_."""

    model_config = SettingsConfigDict(env_prefix="CART_")

    redis_url: str  # required: fail fast if missing
    redis_timeout_seconds: float = 1.0
    cart_ttl_days: int = 7
    max_quantity_per_item: int = 10


settings = Settings()