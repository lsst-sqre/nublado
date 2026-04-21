"""Policy for selecting images based on filter criteria."""

from datetime import datetime
from typing import Annotated

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
)
from pydantic.alias_generators import to_camel
from safir.pydantic import HumanTimedelta
from semver import Version

from ._type import RSPImageType

__all__ = ["ImageFilter", "ImageFilterPolicy"]


def _validate_version(v: Version | str | None) -> Version | None:
    """Validate input to a version field."""
    if v is None:
        return None
    if isinstance(v, Version):
        return v
    return Version.parse(v)


class ImageFilter(BaseModel):
    """Policy for images to display within a given category.

    All specified policies will be applied.  For instance, if the policy
    specifies both age and cutoff version, then an image will have to be
    newer than the specified age, and also have a version greater than or
    equal to the cutoff, in order to be displayed.

    If no policies are specified, no filtering will be performed and all
    images of that category will be displayed.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        extra="forbid",
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

    number: Annotated[
        int | None,
        Field(title="Number", description="Number of images to retain", ge=0),
    ] = None

    age: Annotated[
        HumanTimedelta | None,
        Field(
            title="Age",
            description=(
                "Maximum age of image to retain. Applies only to images based"
                " on weeklies or dailies and is based on the age of the weekly"
                " or daily, not on the age of the build."
            ),
        ),
    ] = None

    cutoff_date: Annotated[
        datetime | None,
        Field(
            title="Cutoff date",
            description=(
                "Minimum date of image to display. Applies only to images"
                " based on weeklies or dailies. Weeklies are assumed to be"
                " built on Thursday."
            ),
        ),
    ] = None

    cutoff_version: Annotated[
        Version | None,
        Field(
            title="Cutoff version",
            description=(
                "Minimum version of image to display. Applies only to images"
                " based on releases or release candidates."
            ),
        ),
        BeforeValidator(_validate_version, json_schema_input_type=str | None),
        PlainSerializer(
            lambda v: None if v is None else str(v), return_type=str | None
        ),
    ] = None


class ImageFilterPolicy(BaseModel):
    """Configuration for display of RSP images.

    Images in the "alias" category are always displayed; images in the
    "unknown" category are never displayed.
    """

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    release: ImageFilter = Field(
        default_factory=ImageFilter, title="Policy for releases"
    )

    weekly: ImageFilter = Field(
        default_factory=ImageFilter, title="Policy for weekly builds"
    )

    daily: ImageFilter = Field(
        default_factory=ImageFilter, title="Policy for daily builds"
    )

    release_candidate: ImageFilter = Field(
        default_factory=ImageFilter, title="Policy for release candidates"
    )

    experimental: ImageFilter = Field(
        default_factory=ImageFilter, title="Policy for experimental builds"
    )

    def for_image_type(self, image_type: RSPImageType) -> ImageFilter | None:
        match image_type:
            case RSPImageType.ALIAS:
                return None  # Do not filter aliases
            case RSPImageType.RELEASE:
                return self.release
            case RSPImageType.WEEKLY:
                return self.weekly
            case RSPImageType.DAILY:
                return self.daily
            case RSPImageType.CANDIDATE:
                return self.release_candidate
            case RSPImageType.EXPERIMENTAL:
                return self.experimental
            case RSPImageType.UNKNOWN:
                return None  # Do not filter unknown tags (subject to change)
