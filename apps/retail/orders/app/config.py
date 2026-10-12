from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings, read from environment variables that start with ORDERS_."""

    model_config = SettingsConfigDict(env_prefix="ORDERS_")

    database_url: str
    catalog_url: str
    cart_url: str
    payment_url: str

    db_pool_min: int = 1
    db_pool_max: int = 10
    db_timeout_seconds: float = 2.0

    # Calls to other services
    call_timeout_seconds: float = 2.0  # design doc: wait at most 2s for payment
    call_attempts: int = 3  # 1 try + 2 retries
    retry_base_delay_seconds: float = 0.2


settings = Settings()
