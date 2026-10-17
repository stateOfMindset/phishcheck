"""Rate limiter unit tests, plus the 429 behaviour of POST /chat (pipeline stubbed: no API calls)."""
import uuid

import pytest

from server import app as app_module
from server.ratelimit import RateLimiter


def test_allows_up_to_the_limit_then_blocks():
    limiter = RateLimiter([(3, 60)])
    assert [limiter.check("ip", now=t) for t in (0, 1, 2)] == [None, None, None]
    assert limiter.check("ip", now=3) == 57   # oldest request (t=0) frees a slot at t=60


def test_window_slides():
    limiter = RateLimiter([(2, 60)])
    limiter.check("ip", now=0)
    limiter.check("ip", now=30)
    assert limiter.check("ip", now=59) == 1
    assert limiter.check("ip", now=60) is None   # t=0 has left the window
    assert limiter.check("ip", now=61) == 29     # now t=30 and t=60 fill it


def test_rejected_requests_are_not_counted():
    limiter = RateLimiter([(1, 10)])
    limiter.check("ip", now=0)
    for t in range(1, 10):
        assert limiter.check("ip", now=t) is not None
    assert limiter.check("ip", now=10) is None   # hammering did not extend the wait


def test_clients_are_independent():
    limiter = RateLimiter([(1, 60)])
    assert limiter.check("a", now=0) is None
    assert limiter.check("b", now=0) is None
    assert limiter.check("a", now=1) is not None


def test_strictest_window_wins():
    limiter = RateLimiter([(10, 60), (3, 86400)])
    for t in (0, 1, 2):
        limiter.check("ip", now=t)
    assert limiter.check("ip", now=120) == 86400 - 120   # minute limit is fine, daily is not


def test_zero_disables_a_limit():
    limiter = RateLimiter([(0, 60)])
    assert all(limiter.check("ip", now=t) is None for t in range(100))


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(app_module.pipeline, "run",
                        lambda session_id, message: {"answer": "stub", "routes": ["direct"]})
    app = app_module.create_app(limiter=RateLimiter([(2, 60)]))
    return app.test_client()


def test_chat_returns_429_with_retry_after(client):
    body = {"session_id": str(uuid.uuid4()), "message": "hello"}
    assert client.post("/chat", json=body).status_code == 200
    assert client.post("/chat", json=body).status_code == 200
    blocked = client.post("/chat", json=body)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
    assert "Too many messages" in blocked.get_json()["error"]


def test_invalid_requests_do_not_use_the_budget(client):
    for _ in range(5):
        assert client.post("/chat", data="not json").status_code == 400
    body = {"session_id": str(uuid.uuid4()), "message": "hello"}
    assert client.post("/chat", json=body).status_code == 200
