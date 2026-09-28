"""Shared pagination primitives used by list endpoints."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PaginationParams:
    """Query parameters for offset-based pagination."""

    page: int = 1
    page_size: int = 20

    MAX_PAGE_SIZE: int = field(default=100, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.page < 1:
            object.__setattr__(self, "page", 1)
        if self.page_size < 1:
            object.__setattr__(self, "page_size", 1)
        if self.page_size > self.MAX_PAGE_SIZE:
            object.__setattr__(self, "page_size", self.MAX_PAGE_SIZE)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


@dataclass(frozen=True)
class Page[T]:
    """A single page of results with total metadata."""

    items: list[T]
    page: int
    page_size: int
    total: int

    @property
    def total_pages(self) -> int:
        if self.page_size <= 0:
            return 0
        return (self.total + self.page_size - 1) // self.page_size

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

    @property
    def has_prev(self) -> bool:
        return self.page > 1
