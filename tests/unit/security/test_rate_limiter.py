"""Rate-limiter boundary, tested deterministically with an injected clock."""

from __future__ import annotations

import pytest
from starlette.requests import Request

from app.security.protection.rate_limiter import InMemoryRateLimiter, forwarded_client_ip
from tests.support.clock import FakeClock


async def test_allows_up_to_limit_then_blocks() -> None:
    limiter = InMemoryRateLimiter(time_source=FakeClock())
    for _ in range(3):
        assert await limiter.allow("k", limit=3, window_seconds=60) is True
    assert await limiter.allow("k", limit=3, window_seconds=60) is False


async def test_window_expiry_restores_allowance() -> None:
    clock = FakeClock()
    limiter = InMemoryRateLimiter(time_source=clock)
    for _ in range(2):
        assert await limiter.allow("k", limit=2, window_seconds=30) is True
    assert await limiter.allow("k", limit=2, window_seconds=30) is False

    clock.advance(31)  # past the window; earlier hits no longer count
    assert await limiter.allow("k", limit=2, window_seconds=30) is True


async def test_keys_are_independent() -> None:
    limiter = InMemoryRateLimiter(time_source=FakeClock())
    assert await limiter.allow("a", limit=1, window_seconds=60) is True
    assert await limiter.allow("b", limit=1, window_seconds=60) is True
    assert await limiter.allow("a", limit=1, window_seconds=60) is False


async def test_expired_keys_are_removed() -> None:
    clock = FakeClock()
    limiter = InMemoryRateLimiter(time_source=clock)
    for n in range(100):
        await limiter.allow(f"client-{n}", limit=5, window_seconds=60)
    assert limiter.tracked_keys() == 100

    clock.advance(61)
    await limiter.allow("fresh", limit=5, window_seconds=60)
    assert limiter.tracked_keys() == 1


async def test_keys_still_inside_their_window_are_kept() -> None:
    clock = FakeClock()
    limiter = InMemoryRateLimiter(time_source=clock)
    await limiter.allow("short", limit=1, window_seconds=10)
    await limiter.allow("long", limit=1, window_seconds=600)

    clock.advance(61)
    await limiter.allow("other", limit=1, window_seconds=10)
    assert limiter.tracked_keys() == 2
    assert await limiter.allow("long", limit=1, window_seconds=600) is False


def _request(peer: str, forwarded_for: str | None = None) -> Request:
    headers = [] if forwarded_for is None else [(b"x-forwarded-for", forwarded_for.encode())]
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


@pytest.mark.parametrize(
    ("hops", "forwarded_for", "expected"),
    [
        (0, "198.51.100.7", "10.0.0.1"),  # untrusted: the header is ignored
        (1, "198.51.100.7", "198.51.100.7"),
        (1, "6.6.6.6, 198.51.100.7", "198.51.100.7"),  # a spoofed prefix is skipped
        (2, "6.6.6.6, 198.51.100.7, 10.0.0.2", "198.51.100.7"),
        (2, "198.51.100.7", "10.0.0.1"),  # fewer entries than proxies: use the peer
        (1, None, "10.0.0.1"),
    ],
)
def test_forwarded_client_ip_trusts_only_the_configured_proxy_hops(
    hops: int, forwarded_for: str | None, expected: str
) -> None:
    assert forwarded_client_ip(_request("10.0.0.1", forwarded_for), trusted_hops=hops) == expected
