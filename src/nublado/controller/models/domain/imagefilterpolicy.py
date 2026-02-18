"""Policy for selecting images based on filter criteria."""

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

from .rspimagetype import RSPImageType

__all__ = ["ImageFilterPolicy", "RSPImageFilterPolicy"]


def _validate_version(v: Version | str | None) -> Version | None:
    """Validate input to a version field."""
    if v is None:
        return None
    if isinstance(v, Version):
        return v
    return Version.parse(v)


class ImageFilterPolicy(BaseModel):
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
        Field(
            title="Number",
            description="Number of images to display.",
            ge=0,
        ),
    ] = None

    age: Annotated[
        HumanTimedelta | None,
        Field(
            title="Age",
            description="Maximum age of image to display.",
        ),
    ] = None

    cutoff_version: Annotated[
        Version | None,
        Field(
            title="Cutoff version",
            description=(
                "Minimum version of image to display."
                " This does not apply to unparseable tags or to"
                " experimental tags not derived from a parseable tag."
            ),
        ),
        BeforeValidator(_validate_version, json_schema_input_type=str | None),
        PlainSerializer(
            lambda v: None if v is None else str(v), return_type=str | None
        ),
    ] = None


class RSPImageFilterPolicy(BaseModel):
    """Configuration for display of RSP images.

    Images in the "alias" category are always displayed; images in the
    "unknown" category are never displayed.
    """

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    release: Annotated[
        ImageFilterPolicy,
        Field(
            title="Release",
            description="Policy for releases to display.",
            default_factory=ImageFilterPolicy,
        ),
    ]

    weekly: Annotated[
        ImageFilterPolicy,
        Field(
            title="Weekly",
            description="Policy for weekly builds to display.",
            default_factory=ImageFilterPolicy,
        ),
    ]

    daily: Annotated[
        ImageFilterPolicy,
        Field(
            title="Daily",
            description="Policy for daily builds to display.",
            default_factory=ImageFilterPolicy,
        ),
    ]

    release_candidate: Annotated[
        ImageFilterPolicy,
        Field(
            title="Release Candidate",
            description="Policy for release candidate builds to display.",
            default_factory=ImageFilterPolicy,
        ),
    ]

    experimental: Annotated[
        ImageFilterPolicy,
        Field(
            title="Experimental",
            description="Policy for experimental builds to display.",
            default_factory=ImageFilterPolicy,
        ),
    ]

    def policy_for_category(
        self, category: RSPImageType
    ) -> ImageFilterPolicy | None:
        match category:
            case RSPImageType.ALIAS:
                return None  # Always show all alias tags
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
                return None  # Show all unknowns (subject to change)
            case _:
                raise ValueError(
                    f"{category!s} does not resolve to known image type"
                )
