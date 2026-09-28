"""Rate limiting.

A small fixed-window limiter behind a `RateLimiter` contract. The in-process
implementation is used by a single instance and by tests (with an injectable
clock so behaviour is deterministic — never dependent on real timing). A
Redis-backed limiter can be dropped in for multi-instance deployments without
touching the `rate_limit` dependency.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Awaitable, Callable

from fastapi import Request

from app.config import get_settings
from app.shared.exceptions import RateLimitError


class RateLimiter(ABC):
    """A fixed-window allow/deny decision for a key."""

    @abstractmethod
    async def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        """Return ``True`` if the request is within the limit, else ``False``."""


class InMemoryRateLimiter(RateLimiter):
    """Fixed-window limiter kept in process memory."""

    def __init__(self, *, time_source: Callable[[], float] = time.time) -> None:
        self._now = time_source
        self._hits: dict[str, list[float]] = defaultdict(list)

    async def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        now = self._now()
        cutoff = now - window_seconds
        hits = [t for t in self._hits[key] if t > cutoff]
        if len(hits) >= limit:
            self._hits[key] = hits
            return False
        hits.append(now)
        self._hits[key] = hits
        return True


_default_limiter = InMemoryRateLimiter()


def client_ip(request: Request) -> str:
    """Best-effort client identity for rate-limit keying."""
    return request.client.host if request.client else "unknown"


def rate_limit(
    *,
    limit: int,
    window_seconds: int = 60,
    limiter: RateLimiter | None = None,
    key_func: Callable[[Request], str] = client_ip,
) -> Callable[[Request], Awaitable[None]]:
    """Build a dependency that enforces ``limit`` hits per ``window_seconds``."""
    active = limiter or _default_limiter

    async def dependency(request: Request) -> None:
        if not get_settings().rate_limit_enabled:
            return
        key = f"{key_func(request)}:{request.url.path}"
        if not await active.allow(key, limit, window_seconds):
            raise RateLimitError()

    return dependency
