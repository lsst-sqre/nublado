"""Base models for rsp_jupyter_client."""

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from enum import Enum, StrEnum
from typing import Literal, override

from pydantic import BaseModel, Field


class NubladoImageClass(StrEnum):
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

    description: str = Field("", title="Human-readable image description")

    debug: bool = Field(False, title="Whether to enable lab debugging")

    @abstractmethod
    def to_spawn_form(self) -> dict[str, str]:
        """Convert to data suitable for posting to Nublado's spawn form.

        Returns
        -------
        dict of str
            Post data to send to the JupyterHub spawn page.
        """


class NubladoImageByReference(NubladoImage):
    """Spawn an image by full Docker reference."""

    image_class: Literal[NubladoImageClass.BY_REFERENCE] = Field(
        NubladoImageClass.BY_REFERENCE, title="Class of image to spawn"
    )

    reference: str = Field(..., title="Docker reference of lab image to spawn")

    @override
    def to_spawn_form(self) -> dict[str, str]:
        result = {
            "image_list": self.reference,
            "size": self.size.value,
        }
        if self.debug:
            result["enable_debug"] = "true"
        return result


class NubladoImageByTag(NubladoImage):
    """Spawn an image by image tag."""

    image_class: Literal[NubladoImageClass.BY_TAG] = Field(
        NubladoImageClass.BY_TAG, title="Class of image to spawn"
    )

    tag: str = Field(..., title="Tag of image to spawn")

    @override
    def to_spawn_form(self) -> dict[str, str]:
        result = {"image_tag": self.tag, "size": self.size.value}
        if self.debug:
            result["enable_debug"] = "true"
        return result


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

    @override
    def to_spawn_form(self) -> dict[str, str]:
        result = {
            "image_class": self.image_class.value,
            "size": self.size.value,
        }
        if self.debug:
            result["enable_debug"] = "true"
        return result
