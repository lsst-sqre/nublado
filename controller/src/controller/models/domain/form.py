"""Internal models for spawner form construction."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "FormSize",
    "MenuImage",
    "MenuImages",
]


@dataclass
class FormSize:
    """Holds a representation of an image size for spawner forms."""

    name: str
    """Human-readable name for this lab size."""

    cpu: str
    """CPU limit."""

    memory: str
    """Memory limit."""

    @property
    def description(self) -> str:
        return f"{self.name} ({self.cpu} CPU, {self.memory} RAM)"


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
