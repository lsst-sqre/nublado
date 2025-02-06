"""Models for image display policy."""

import datetime
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from semver.version import VersionInfo

__all__ = ["IndividualImageClassPolicy", "RSPImagePolicy"]


def _empty_str_is_none(inp: Any) -> Any:
    if isinstance(inp, str) and inp == "":
        return None
    return inp


class IndividualImageClassPolicy(BaseModel):
    """Policy for images to display within a given class.

    The policy has both a 'number' and an 'age' field.

    'number' means: display that many of whatever image class this is
    attached to.  `-1` or `None` are interpreted as "do not filter
    (i.e. show all of this image class)" and `0` means "display no
    images of this class."  This has historically been the only filter
    option.

    'age' means: display any items of the class whose age is the
    specified age or less.  This age is a duration, specified by a
    string as accepted by Safir's HumanTimeDelta.  The empty string
    means "do not filter this class at all."

    'cutoff_version' means: display any items of this class whose semantic
    version is this large or larger.  This only makes sense for dailies,
    weeklies, releases, release candidates, and experimentals derived from
    one of those builds.

    'filter_empty' governs the behavior when a policy is applied to an image
    that does not have data for that category (e.g. an 'age' policy exists,
    but the image age is 'None' because it could not be determined).  If
    'filter_empty' is 'True', the image will not be displayed, and if 'False'
    the image will be displayed.

    If multiple of these are specified, the intersection of these policies
    will be applied.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    filter_empty: Annotated[
        bool,
        Field(
            title="Filter empty",
            description=(
                "If a filter category is not 'None', but the corresponding"
                " value is 'None' (e.g. there is an age filter, but the image"
                " age could not be determined and thus the image 'age' field"
                " is 'None'), if this is set to 'True', the image will not be"
                " displayed; if it is 'False', it will be displayed.  The"
                " default is 'False'."
            ),
        ),
    ] = False

    age: Annotated[
        datetime.timedelta | None,
        Field(
            BeforeValidator(_empty_str_is_none),
            title="Age",
            description="Maximum age of image to retain.",
        ),
    ] = None

    cutoff_version: Annotated[
        VersionInfo | None,
        Field(
            BeforeValidator(_empty_str_is_none),
            title="Cutoff Version",
            description="Minimum version of image to retain.",
        ),
    ] = None

    number: Annotated[
        int | None,
        Field(
            BeforeValidator(_empty_str_is_none),
            title="Number",
            description="Number of images to retain.",
        ),
    ] = None


class RSPImagePolicy(BaseModel):
    """Aliases are never filtered.  Default for everything else is "do not
    filter".
    """

    release: Annotated[
        IndividualImageClassPolicy | None,
        Field(title="Release", description="Policy for releases to display."),
    ] = None

    weekly: Annotated[
        IndividualImageClassPolicy | None,
        Field(
            title="Weekly", description="Policy for weekly builds to display."
        ),
    ] = None

    daily: Annotated[
        IndividualImageClassPolicy | None,
        Field(
            title="Daily", description="Policy for daily builds to display."
        ),
    ] = None

    release_candidate: Annotated[
        IndividualImageClassPolicy | None,
        Field(
            title="Release Candidate",
            description=(
                "Policy for release candidate builds to display.",
                " Note that, in the service layer, there will be"
                " an implicit policy that release candidates will"
                " only ever be displayed for versions that themselves"
                " are unreleased.  For instance, if 35.0.1rc2 would"
                " otherwise be displayed, but release 35.0.1 is"
                " minted, 35.0.1rc2 will no longer be displayed.",
            ),
        ),
    ] = None

    experimental: Annotated[
        IndividualImageClassPolicy | None,
        Field(
            title="Experimental",
            description="Policy for experimental builds to display.",
        ),
    ] = None

    unknown: Annotated[
        IndividualImageClassPolicy | None,
        Field(
            title="Unknown",
            description=(
                "Policy for builds without parseable RSP tags to display."
            ),
        ),
    ] = None
