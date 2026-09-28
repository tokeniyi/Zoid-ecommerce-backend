"""Rate-limiter boundary, tested deterministically with an injected clock."""

from __future__ import annotations

from app.security.protection.rate_limiter import InMemoryRateLimiter


class FakeClock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


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
