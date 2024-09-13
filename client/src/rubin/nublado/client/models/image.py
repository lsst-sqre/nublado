"""Base models for rsp_jupyter_client."""

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "NubladoImage",
    "NubladoImageClass",
    "NubladoImageSize",
]


class NubladoImageClass(str, Enum):
    """Possible ways of selecting an image."""

    __slots__ = ()

    RECOMMENDED = "recommended"
    LATEST_RELEASE = "latest-release"
    LATEST_WEEKLY = "latest-weekly"
    LATEST_DAILY = "latest-daily"
    BY_REFERENCE = "by-reference"
    BY_TAG = "by-tag"


class NubladoImageSize(Enum):
    """Acceptable sizes of images to spawn."""

    Fine = "Fine"
    Diminutive = "Diminutive"
    Tiny = "Tiny"
    Small = "Small"
    Medium = "Medium"
    Large = "Large"
    Huge = "Huge"
    Gargantuan = "Gargantuan"
    Colossal = "Colossal"


class NubladoImage(BaseModel, metaclass=ABCMeta):
    """Base class for different ways of specifying the lab image to spawn."""

    # Ideally this would just be class, but it is a keyword and adding all the
    # plumbing to correctly serialize Pydantic models by alias instead of
    # field name is tedious and annoying. Live with the somewhat verbose name.
    image_class: NubladoImageClass = Field(
        ...,
        title="Class of image to spawn",
    )

    size: NubladoImageSize = Field(
        NubladoImageSize.Large,
        title="Size of image to spawn",
        description="Must be one of the sizes understood by Nublado.",
    )

    debug: bool = Field(False, title="Whether to enable lab debugging")

    @abstractmethod
    def to_spawn_form(self) -> dict[str, str]:
        """Convert to data suitable for posting to Nublado's spawn form.

        Returns
        -------
        dict of str
            Post data to send to the JupyterHub spawn page.
        """


class NubladoImageByClass(NubladoImage):
    """Spawn the recommended image."""

    image_class: Literal[
        NubladoImageClass.RECOMMENDED,
        NubladoImageClass.LATEST_RELEASE,
        NubladoImageClass.LATEST_WEEKLY,
        NubladoImageClass.LATEST_DAILY,
    ] = Field(
        NubladoImageClass.RECOMMENDED,
        title="Class of image to spawn",
    )

    def to_spawn_form(self) -> dict[str, str]:
        result = {
            "image_class": self.image_class.value,
            "size": self.size.value,
        }
        if self.debug:
            result["enable_debug"] = "true"
        return result
