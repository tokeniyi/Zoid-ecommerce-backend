"""A small Result type for operations that may fail without raising.

Domain/application code may return `Result` to make failure explicit while the
API layer translates it into HTTP responses. Exceptions remain available for
truly exceptional paths.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Result[T, E]:
    """Represents either a success value (`ok`) or an error (`err`)."""

    ok: T | None = None
    err: E | None = None
    _has_value: bool = True

    @property
    def is_success(self) -> bool:
        return self._has_value

    @property
    def succeeded(self) -> bool:
        return self._has_value

    @classmethod
    def success(cls, value: T) -> Result[T, E]:
        return cls(ok=value, err=None, _has_value=True)

    @classmethod
    def failure(cls, error: E) -> Result[T, E]:
        return cls(ok=None, err=error, _has_value=False)
