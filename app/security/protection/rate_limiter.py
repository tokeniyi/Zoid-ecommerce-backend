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
    """Fixed-window limiter kept in process memory.

    Keys whose hits have all aged out are swept at most once per
    ``sweep_interval`` seconds, so memory tracks recent clients rather than
    every client ever seen.
    """

    def __init__(
        self,
        *,
        time_source: Callable[[], float] = time.time,
        sweep_interval: float = 60.0,
    ) -> None:
        self._now = time_source
        self._sweep_interval = sweep_interval
        self._hits: dict[str, list[float]] = {}
        self._windows: dict[str, int] = {}
        self._next_sweep = time_source() + sweep_interval

    async def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        now = self._now()
        if now >= self._next_sweep:
            self._sweep(now)
        cutoff = now - window_seconds
        hits = [t for t in self._hits.get(key, ()) if t > cutoff]
        self._hits[key] = hits
        self._windows[key] = window_seconds
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True

    def tracked_keys(self) -> int:
        return len(self._hits)

    def _sweep(self, now: float) -> None:
        expired = [
            key
            for key, hits in self._hits.items()
            if not hits or hits[-1] <= now - self._windows[key]
        ]
        for key in expired:
            del self._hits[key]
            del self._windows[key]
        self._next_sweep = now + self._sweep_interval


_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    """The process-wide limiter for the configured ``RATE_LIMIT_BACKEND``."""
    global _limiter
    if _limiter is None:
        backend = get_settings().rate_limit_backend
        if backend != "memory":  # pragma: no cover - settings validation rejects others
            raise ValueError(f"Unsupported rate-limit backend: {backend!r}")
        _limiter = InMemoryRateLimiter()
    return _limiter


def use_rate_limiter(limiter: RateLimiter | None) -> None:
    """Install ``limiter`` process-wide; ``None`` rebuilds from settings on next use."""
    global _limiter
    _limiter = limiter


def forwarded_client_ip(request: Request, *, trusted_hops: int) -> str:
    """The client address, believing ``X-Forwarded-For`` only from trusted proxies.

    Each of the ``trusted_hops`` proxies in front of the app appends the address
    it received the request from, so the client is that many entries from the
    right. Anything further left was written by the client and is ignored.
    """
    peer = request.client.host if request.client else "unknown"
    if trusted_hops <= 0:
        return peer
    header = request.headers.get("x-forwarded-for", "")
    entries = [entry.strip() for entry in header.split(",") if entry.strip()]
    if len(entries) < trusted_hops:
        return peer
    return entries[-trusted_hops]


def client_ip(request: Request) -> str:
    """Client identity for rate-limit keying (see ``RATE_LIMIT_TRUSTED_PROXY_HOPS``)."""
    return forwarded_client_ip(request, trusted_hops=get_settings().rate_limit_trusted_proxy_hops)


def rate_limit(
    *,
    limit: int | Callable[[], int],
    window_seconds: int = 60,
    limiter: RateLimiter | None = None,
    key_func: Callable[[Request], str] = client_ip,
) -> Callable[[Request], Awaitable[None]]:
    """Build a dependency that enforces ``limit`` hits per ``window_seconds``.

    ``limit`` may be a callable so a route can follow a setting that is read at
    request time rather than when the route module is imported.
    """

    async def dependency(request: Request) -> None:
        if not get_settings().rate_limit_enabled:
            return
        active = limiter or get_rate_limiter()
        allowed = limit() if callable(limit) else limit
        key = f"{key_func(request)}:{request.url.path}"
        if not await active.allow(key, allowed, window_seconds):
            raise RateLimitError()

    return dependency
