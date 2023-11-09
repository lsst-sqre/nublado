"""Internal models returned by image service methods."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "MenuImage",
    "MenuImages",
]


@dataclass(frozen=True, slots=True)
class MenuImage:
    """A single spawnable image."""

    reference: str
    """Docker reference."""

    name: str
    """Human-readable name."""


@dataclass(frozen=True, slots=True)
class MenuImages:
    """All available spawnable images."""

    menu: list[MenuImage]
    """Images that should appear as regular menu choices."""

    dropdown: list[MenuImage]
    """Extra images to populate the dropdown."""
