"""Internal models returned by image service methods."""

from dataclasses import dataclass
from typing import Self

from pydantic import BaseModel, Field

from .rspimage import RSPImage, RSPImageCollection

__all__ = [
    "MenuImage",
    "MenuImages",
    "NodeData",
]


class MenuImage(BaseModel):
    """A single spawnable image."""

    reference: str = Field(..., title="Docker reference")

    name: str = Field(..., title="Human-readable name")

    @classmethod
    def from_rsp_image(cls, image: RSPImage) -> Self:
        """Create a menu image from an RSP image."""
        return cls(
            reference=image.reference_with_digest, name=image.display_name
        )


class MenuImages(BaseModel):
    """All available spawnable images."""

    menu: list[MenuImage] = Field(..., title="Regular menu choices")

    dropdown: list[MenuImage] = Field(..., title="Additional dropdown choices")


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
