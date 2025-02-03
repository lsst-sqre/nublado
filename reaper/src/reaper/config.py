"""Configuration for reaper for container registries."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Annotated, Any, ClassVar, Self

import yaml
from pydantic import (
    BeforeValidator,
    Field,
    HttpUrl,
    SecretStr,
    model_validator,
)
from safir.pydantic import CamelCaseModel, validate_exactly_one_of

from controller.models.domain.registryimage import (
    RegistryImageVersionClass,
    RegistryCategory,
)


def _empty_str_is_none(inp: Any) -> Any:
    if isinstance(inp, str) and inp == "":
        return None
    return inp


class RegistryAuth(CamelCaseModel):
    """Generic authentication item for a container registry."""

    realm: Annotated[
        str | None,
        Field(
            title="Realm",
            description=(
                "Realm (generally, hostname) for which authentication is valid."
            ),
            examples="docker.io",
        ),
    ] = None

    username: Annotated[
        str | None,
        Field(
            title="Username",
            description="Username (if any) for authentication.",
            examples="fbooth",
        ),
    ] = None

    password: Annotated[
        SecretStr | None,
        Field(
            title="Password",
            description="Secret (password or token) for authentication.",
            examples="hunter2",
        ),
    ] = None


class IndividualKeepPolicy(CamelCaseModel):
    """The policy has both a 'number' and an 'age' field.  'number'
    means keep that many of whatever image class this is attached to.
    `-1` or `None` means "do not reap that class at all". and `0`
    means "purge them all".  'age' means keep anything that is the
    specified duration or less.  Durations are specified as strings as
    accepted by Safir's HumanTimeDelta, and here again the empty
    string means "do not reap that class at all".

    You must specify exactly one of these.
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


class LatestSemverKeepers(CamelCaseModel):
    """How to choose items to keep for latest major semver release.
    Default is "do not purge".
    """

    minor: Annotated[
        IndividualKeepPolicy,
        Field(
            title="Minor",
            description=(
                "Policy for minor versions within latest major semanticversion to keep."
            ),
        ),
    ]

    patch: Annotated[
        IndividualKeepPolicy,
        Field(
            title="Patch",
            description=(
                "Policy for patch versions within a given minor version "
                "within latest major semantic version to keep."
            ),
        ),
    ]

    build: Annotated[
        IndividualKeepPolicy,
        Field(
            title="Build",
            description=(
                "Policy for build versions within a given patch version "
                " within a given minor version within latest major semantic "
                "version to keep."
            ),
        ),
    ]


class OlderSemverKeepers(CamelCaseModel):
    """How to choose items to keep for previous major semver releases.
    Default is "do not purge".
    """

    major: Annotated[
        IndividualKeepPolicy,
        Field(
            title="Major",
            description=("Policy for how many major semantic versions to keep."),
        ),
    ]

    minor: Annotated[
        IndividualKeepPolicy,
        Field(
            title="Minor",
            description=(
                "Policy for minor versions within a given major semantic "
                "version to keep."
            ),
        ),
    ]

    patch: Annotated[
        IndividualKeepPolicy,
        Field(
            title="Patch",
            description=(
                "Policy for patch versions within a given minor version "
                "within a given major semantic version to keep."
            ),
        ),
    ]

    build: Annotated[
        IndividualKeepPolicy,
        Field(
            title="Build",
            description=(
                "Policy for build versions within a given patch version "
                " within a given minor version within a given major semantic "
                "version to keep."
            ),
        ),
    ]


class SemverKeepers(CamelCaseModel):
    """Within each of latest_major and older, how many minor versions,
    how many patch versions within each of those, and how many builds of each
    of those, to keep.  Older also has a major version number.  For instance,
    older.major might be 3, and then when version 5.0 came out, you would
    keep some images for the 2.x.y, 3.x.y, and 4.x.y series, but no 1.x images.
    """

    latest_major: Annotated[
        LatestSemverKeepers,
        Field(
            title="Latest Major",
            description=("Policy for images to keep in latest major semantic version."),
        ),
    ]

    older: Annotated[
        OlderSemverKeepers,
        Field(
            title="Older",
            description=(
                "Policy for images to keep for older major semantic versions."
            ),
        ),
    ]


class RSPKeepers(CamelCaseModel):
    """Aliases are never purged.  Default for everything else is "do not
    purge".
    """

    release: Annotated[
        IndividualKeepPolicy,
        Field(title="Release", description="Policy for releases to keep."),
    ]

    weekly: Annotated[
        IndividualKeepPolicy,
        Field(title="Weekly", description="Policy for weekly builds to keep."),
    ]

    daily: Annotated[
        IndividualKeepPolicy,
        Field(title="Daily", description="Policy for daily builds to keep."),
    ]

    release_candidate: Annotated[
        IndividualKeepPolicy,
        Field(
            title="Release Candidate",
            description="Policy for release candidate builds to keep.",
        ),
    ]

    experimental: Annotated[
        IndividualKeepPolicy,
        Field(
            title="Experimental",
            description="Policy for experimental builds to keep.",
        ),
    ]

    unknown: Annotated[
        IndividualKeepPolicy,
        Field(
            title="Unknown",
            description=("Policy for builds without parseable RSP tags to keep."),
        ),
    ]


class KeepPolicy(CamelCaseModel):
    """How to choose which images within each image category to keep.
    The default is to purge nothing.
    """

    untagged: Annotated[
        IndividualKeepPolicy | None,
        Field(title="Untagged", description="Policy for untagged builds to keep."),
    ] = None

    semver: Annotated[
        SemverKeepers | None,
        Field(
            title="Semantic Version",
            description="Policy for semantic version-tagged builds to keep.",
        ),
    ] = None

    rsp: Annotated[
        RSPKeepers | None,
        Field(
            title="RSP",
            description="Policy for RSP-format-tagged builds to keep.",
        ),
    ] = None


class RegistryConfig(CamelCaseModel):
    """Configuration to talk to a particular container registry."""

    registry: Annotated[
        HttpUrl,
        Field(
            title="Registry",
            description="URL of registry host",
            examples=[HttpUrl("https://docker.io/")],
        ),
    ]

    owner: Annotated[
        str,
        Field(
            title="Owner",
            description="Usually repo owner; at GAR, project ID",
            examples=["lsst-sqre"],
        ),
    ]

    repository: Annotated[
        str,
        Field(
            title="Repository",
            description="Repository name",
            examples=["sciplat-lab"],
        ),
    ]

    category: Annotated[
        RegistryCategory,
        Field(
            title="Category",
            description="Category of registry",
            examples=RegistryCategory.GAR,
        ),
    ]

    keep: Annotated[
        KeepPolicy,
        Field(
            title="Keep Policy",
            description="Policy for which images to retain.",
        ),
    ]

    image_version_class: Annotated[
        RegistryImageVersionClass,
        Field(
            title="Image version class",
            description=(
                "Image version class describing how tags in this repository "
                "are structured (semver, RSP format, or untagged)."
            ),
            examples=[RegistryImageVersionClass.RSP],
        ),
    ] = RegistryImageVersionClass.RSP

    namespace: Annotated[
        str | None,
        Field(
            title="Namespace",
            description="Intermediate layer if any; at GAR: 'sciplat'",
        ),
    ] = None

    auth: Annotated[
        RegistryAuth | None,
        Field(
            title="Registry Auth",
            description="Authentication details for specified registry.",
        ),
    ] = None

    skip_tags: ClassVar[
        Annotated[
            set[str],
            Field(
                title="Skip tags",
                description=(
                    "If an image has any of these tags, mark it as exempt from reaping"
                ),
            ),
        ]
    ] = set()

    dry_run: Annotated[
        bool,
        Field(
            title="Dry run",
            description="Do not actually delete any images from registry.",
        ),
    ] = True

    debug: Annotated[
        bool,
        Field(
            title="Debug",
            description="Much more verbose logging in human-readable format.",
        ),
    ] = True

    input_file: Annotated[
        Path | None,
        Field(
            title="Input file",
            description=(
                "If supplied, use repository data from this file, rather than "
                "scanned from actual repository."
            ),
        ),
    ] = None


class Config(CamelCaseModel):
    """Configuration for multiple registries."""

    registries: Annotated[
        list[RegistryConfig],
        Field(
            title="Registries",
            description="List of registries to be reaped.",
        ),
    ]

    @classmethod
    def from_file(cls, path: Path) -> Self:
        return cls.model_validate(yaml.safe_load(path.read_text()))
