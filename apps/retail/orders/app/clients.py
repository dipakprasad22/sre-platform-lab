"""Calls to other services, with timeouts and retries."""

import logging
import random
import time

import httpx

from app.config import settings

log = logging.getLogger("orders.clients")


class CallFailed(Exception):
    """The call failed after all retries.

    ambiguous=True means we do NOT know if the other side did the work
    (for example a read timeout: the request may have arrived and been processed).
    """

    def __init__(self, message: str, ambiguous: bool):
        super().__init__(message)
        self.ambiguous = ambiguous


def call(client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
    """Send a request. Retry only on network problems and 5xx answers.

    Only use this for requests that are safe to repeat (idempotent).
    4xx answers are returned straight away: retrying a bad request never helps.
    """
    last_error = "unknown"
    ambiguous = False
    for attempt in range(1, settings.call_attempts + 1):
        try:
            resp = client.request(
                method, url, timeout=settings.call_timeout_seconds, **kwargs
            )
            if resp.status_code < 500:
                return resp
            last_error, ambiguous = f"HTTP {resp.status_code}", False
        except httpx.ConnectTimeout as exc:
            last_error, ambiguous = f"connect timeout: {exc}", False
        except httpx.ConnectError as exc:
            last_error, ambiguous = f"connect error: {exc}", False
        except httpx.TimeoutException as exc:
            # The request may have been received and processed. We cannot tell.
            last_error, ambiguous = f"timeout: {exc}", True
        except httpx.TransportError as exc:
            last_error, ambiguous = f"transport error: {exc}", True

        log.warning(
            "call %s %s failed (attempt %d/%d): %s",
            method,
            url,
            attempt,
            settings.call_attempts,
            last_error,
        )
        if attempt < settings.call_attempts:
            # Exponential backoff with jitter: 0.2s, 0.4s, ... plus a little randomness,
            # so many clients retrying at once do not hit the service in waves.
            delay = settings.retry_base_delay_seconds * 2 ** (attempt - 1)
            time.sleep(delay + random.uniform(0, delay / 2))

    raise CallFailed(f"{method} {url}: {last_error}", ambiguous=ambiguous)
