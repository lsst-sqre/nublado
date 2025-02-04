"""Model for spawner menu."""

from typing import Annotated

from pydantic import BaseModel, Field

from ...exceptions import MissingImageCountError
from ..v1.prepuller import (
    DockerSourceOptions,
    GARSourceOptions,
    PrepullerOptions,
)
from .imagepolicy import RSPImagePolicy

__all__ = ["ImageDisplayPolicy", "SpawnerMenuOptions"]


class ImageDisplayPolicy(BaseModel):
    """Holds image display policies for spawner main and dropdown menus."""

    main: Annotated[
        RSPImagePolicy | None,
        Field(title="Image display policy for spawner main menu"),
    ] = None

    dropdown: Annotated[
        RSPImagePolicy | None,
        Field(title="Image display policy for spawner dropdown menu"),
    ] = None


class SpawnerMenuOptions(BaseModel):
    """Options needed to construct the spawner menu.

    This class and PrepullerOptions are largely the same.  If we prefer we
    could change the API and get rid of PrepullerOptions.
    """

    source: Annotated[
        DockerSourceOptions | GARSourceOptions, Field(title="Source of images")
    ]

    display_policy: Annotated[
        ImageDisplayPolicy | None,
        Field(title="Display policy for spawner images"),
    ] = None

    recommended_tag: Annotated[
        str,
        Field(
            title="Tag of recommended image",
            description=(
                "This image will be shown first on the menu as the default"
                " choice."
            ),
            examples=["recommended"],
        ),
    ] = "recommended"

    cycle: Annotated[
        int | None,
        Field(
            title="Limit to this cycle number (XML schema version)",
            description=(
                "Telescope and Site images contain software implementing a"
                " specific XML schema version, and it is not safe to use"
                " software using a different XML schema version. If this is"
                " set, only images with a matching cycle will be shown in the"
                " spawner menu."
            ),
            examples=[27],
        ),
    ] = None

    pin: Annotated[
        list[str],
        Field(
            title="List of image tags to prepull and pin to the menu",
            description=(
                "Forces images to be cached and pinned to the menu even when"
                " they would not normally be prepulled (not recommended or"
                " within the latest dailies, weeklies, or releases). This can"
                " be used to add additional images to the menu or to force"
                " resolution of the image underlying the recommended tag when"
                " Docker is used as the image source so that we can give it a"
                " proper display name."
            ),
            examples=[["d_2077_10_23"]],
        ),
    ] = []

    alias_tags: Annotated[
        list[str],
        Field(
            title="Additional alias tags",
            description=(
                "These tags will automatically be recognized as alias tags"
                " rather than unknown tags, which results in different sorting"
                " and better human-readable descriptions."
            ),
            examples=[["recommended_cycle0027"]],
        ),
    ] = []

    def to_prepuller_options(self) -> PrepullerOptions:
        """Construct PrepullerOptions from SpawnerMenuOptions.

        The underlying presumption, that may not be obvious at first glance,
        is that the main menu on the Spawner Menu contains definitionally
        exactly those images that should be prepulled.
        """
        if self.display_policy is None or self.display_policy.main is None:
            raise MissingImageCountError(
                "Display policy for 'main' in spawner menu options must"
                " be defined"
            )
        pol = self.display_policy.main
        if (
            pol.release is None
            or pol.release.number is None
            or pol.weekly is None
            or pol.weekly.number is None
            or pol.daily is None
            or pol.daily.number is None
        ):
            raise MissingImageCountError(
                "All of 'daily', 'weekly', and 'release' must be defined and"
                " numeric in display policy to generate prepuller options"
            )
        return PrepullerOptions(
            source=self.source,
            recommended_tag=self.recommended_tag,
            cycle=self.cycle,
            pin=self.pin,
            alias_tags=self.alias_tags,
            num_releases=pol.release.number,
            num_weeklies=pol.weekly.number,
            num_dailies=pol.daily.number,
        )
