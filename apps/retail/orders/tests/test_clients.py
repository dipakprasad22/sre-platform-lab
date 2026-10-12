import httpx
import pytest

from app import clients
from app.config import settings


def make_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(clients.time, "sleep", lambda s: None)


def test_retries_5xx_then_succeeds():
    answers = iter([503, 503, 200])
    seen = []

    def handler(request):
        seen.append(1)
        return httpx.Response(next(answers))

    resp = clients.call(make_client(handler), "GET", "http://svc/x")
    assert resp.status_code == 200
    assert len(seen) == 3


def test_does_not_retry_4xx():
    seen = []

    def handler(request):
        seen.append(1)
        return httpx.Response(409)

    assert clients.call(make_client(handler), "GET", "http://svc/x").status_code == 409
    assert len(seen) == 1


def test_read_timeout_is_ambiguous():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(clients.CallFailed) as err:
        clients.call(make_client(handler), "GET", "http://svc/x")
    assert err.value.ambiguous is True


def test_connect_error_is_not_ambiguous():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(clients.CallFailed) as err:
        clients.call(make_client(handler), "GET", "http://svc/x")
    assert err.value.ambiguous is False
    assert settings.call_attempts == 3
