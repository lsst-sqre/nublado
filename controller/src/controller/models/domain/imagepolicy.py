"""Policy for selecting images based on filter criteria."""

from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from pydantic.alias_generators import to_camel
from safir.pydantic import HumanTimedelta
from semver import Version

__all__ = ["DropdownMenuPolicy", "IndividualImageClassPolicy"]


class IndividualImageClassPolicy(BaseModel):
    """Policy for images to display within a given class.

    The policy has a 'number', an 'age', and a 'cutoff_version' field.  All
    are optional.

    All specified policies will be applied.  For instance, if the policy
    specifies both age and cutoff version, then an image will have to be
    newer than the specified age, and also have a version greater than or
    equal to the cutoff, in order to be displayed.

    If no policies are specified, no filtering will be performed and all
    images of that class will be displayed.
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
        BeforeValidator(lambda v: v if not isinstance(v, str) else Version(v)),
        Field(
            title="Cutoff Version",
            description=(
                "Minimum version of image to display."
                " This does not apply to unparseable tags or to"
                " experimental tags not derived from a parseable tag."
            ),
        ),
    ] = None


class DropdownMenuPolicy(BaseModel):
    """Configuration for the spawner page dropdown menu."""

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )
    release: Annotated[
        IndividualImageClassPolicy,
        Field(
            title="Release",
            description="Policy for releases to display.",
            default_factory=IndividualImageClassPolicy,
        ),
    ]

    weekly: Annotated[
        IndividualImageClassPolicy,
        Field(
            title="Weekly",
            description="Policy for weekly builds to display.",
            default_factory=IndividualImageClassPolicy,
        ),
    ]

    daily: Annotated[
        IndividualImageClassPolicy,
        Field(
            title="Daily",
            description="Policy for daily builds to display.",
            default_factory=IndividualImageClassPolicy,
        ),
    ]

    release_candidate: Annotated[
        IndividualImageClassPolicy,
        Field(
            title="Release Candidate",
            description=("Policy for release candidate builds to display.",),
            default_factory=IndividualImageClassPolicy,
        ),
    ]

    experimental: Annotated[
        IndividualImageClassPolicy,
        Field(
            title="Experimental",
            description="Policy for experimental builds to display.",
            default_factory=IndividualImageClassPolicy,
        ),
    ]

    unknown: Annotated[
        IndividualImageClassPolicy,
        Field(
            title="Unknown",
            description=(
                "Policy for builds without parseable RSP tags to display."
            ),
            default_factory=IndividualImageClassPolicy,
        ),
    ]
