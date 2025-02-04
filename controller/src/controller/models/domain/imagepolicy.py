"""Models for image display policy."""

import datetime
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field, model_validator
from safir.pydantic import validate_exactly_one_of


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

    Exactly one of these must be specified.
    """

    age: Annotated[
        datetime.timedelta | None,
        Field(
            BeforeValidator(_empty_str_is_none),
            title="Age",
            description="Maximum age of image to retain.",
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

    _validate_options = model_validator(mode="after")(
        validate_exactly_one_of("number", "age")
    )


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
            description="Policy for release candidate builds to display.",
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
