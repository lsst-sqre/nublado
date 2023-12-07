"""Internal models returned by image service methods."""

from __future__ import annotations

from dataclasses import dataclass

from .rspimage import RSPImageCollection

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


@dataclass(frozen=True)
class NodeData:
    """Cached data about a Kubernetes node.

    This data is used to answer prepuller questions and as source data for the
    prepuller status, but the prepuller status API presents it in a slightly
    different way and with more primitive data types.
    """

    name: str
    """Name of the node."""

    images: RSPImageCollection
    """Images of interest present on that node."""

    eligible: bool = True
    """Whether this node is eligible for prepulling."""

    comment: str | None = None
    """Reason why images aren't prepulled to this node."""
