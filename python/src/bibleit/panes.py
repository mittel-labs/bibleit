from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass
class PaneRegistry(Generic[T]):
    views: list[T] = field(default_factory=list)
    active_view: T | None = None
    maximized_view: T | None = None

    def has(self, view: T | None) -> bool:
        return any(candidate is view for candidate in self.views)

    def add(self, view: T) -> None:
        self.views.append(view)
        self.active_view = view

    def remove(self, view: T) -> T | None:
        index = self.index(view)
        if index is None:
            return self.active()

        self.views.pop(index)
        replacement = self.views[min(index, len(self.views) - 1)] if self.views else None

        if self.active_view is view:
            self.active_view = replacement

        if self.maximized_view is view:
            self.maximized_view = None

        if self.active_view is not None and not self.has(self.active_view):
            self.active_view = replacement

        if self.maximized_view is not None and not self.has(self.maximized_view):
            self.maximized_view = None

        return self.active()

    def active(self, focused_view: T | None = None) -> T | None:
        if self.maximized_view is not None:
            return self.maximized_view

        if self.has(focused_view):
            return focused_view

        if self.has(self.active_view):
            return self.active_view

        return self.views[0] if self.views else None

    def set_active(self, view: T | None) -> bool:
        if not self.has(view):
            return False

        self.active_view = view
        return True

    def set_maximized(self, view: T | None) -> T | None:
        previous = self.maximized_view
        self.maximized_view = view if self.has(view) else None

        if self.maximized_view is not None:
            self.active_view = self.maximized_view
        elif self.has(previous):
            self.active_view = previous

        return self.active()

    def index(self, view: T | None) -> int | None:
        for index, candidate in enumerate(self.views):
            if candidate is view:
                return index

        return None

    def cycle(self, direction: int, focused_view: T | None = None) -> T | None:
        if len(self.views) < 2:
            return None

        index = self.index(self.active(focused_view))
        if index is None:
            return None

        return self.views[(index + direction) % len(self.views)]

    def by_number(self, number: int) -> T | None:
        index = number - 1
        if index < 0 or index >= len(self.views):
            return None

        return self.views[index]
