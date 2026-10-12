from pydantic_settings import BaseSettings, SettingsConfigDict  # type: ignore[import-not-found]


class Settings(BaseSettings):
    """Starting chaos settings, read from environment variables that start with PAYMENT_."""

    model_config = SettingsConfigDict(env_prefix="PAYMENT_")

    failure_rate: float = 0.0  # share of requests that fail with 503 (our "outage")
    decline_rate: float = 0.0  # share of payments the "bank" declines (a normal 4xx)
    latency_ms: int = 0  # extra delay added to every payment


settings = Settings()