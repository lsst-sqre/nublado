"""Model for sanitized configuration passed to Lab as mounted ConfigMap."""

from __future__ import annotations

from typing import Annotated

from pydantic import (
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
)
from pydantic.alias_generators import to_camel

from ...config import (
    LabFileBrowserRoot,
    SharedLabConfig,
    UserHomeDirectorySchema,
)
from ...units import memory_to_bytes

__all__ = ["LabConfigMap"]


class LabConfigMap(SharedLabConfig):
    """Items to pass to the Lab at startup as mounted ConfigMap.

    Some of these items come from the SharedLabConfig; others are included
    from different sources.
    """

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    container_size: Annotated[
        str,
        Field(
            title="Container size",
            description="Human-readable container size",
            examples=["Large (4.0 CPU, 16Gi RAM)"],
        ),
    ]

    cpu_guarantee: Annotated[
        int | float | str,
        Field(
            title="CPU guarantee",
            description="Number of CPU cores guaranteed for Lab",
            examples=[4, 2.0, "200m"],
        ),
    ]

    cpu_limit: Annotated[
        int | float | str,
        Field(
            title="CPU limit",
            description="Maximum number of CPU cores usable by Lab",
            examples=[4, 2.0, "200m"],
        ),
    ]

    debug: Annotated[
        bool,
        Field(
            title="Debug",
            description="Enable debug logging",
        ),
    ] = False

    file_browser_root: Annotated[
        str,
        Field(
            title="JupyterLab file browser root",
            description=(
                "Whether to allow traversal in the UI file browser all"
                " the way up to the container root, or only as high as"
                " the user home directory."
            ),
        ),
    ] = LabFileBrowserRoot.HOME.value

    homedir_schema: Annotated[
        str,
        Field(
            title="Schema for user homedir construction",
            description=(
                "Determines how the username portion of the home directory"
                " path is constructed."
            ),
        ),
    ] = UserHomeDirectorySchema.USERNAME.value

    image_description: Annotated[
        str,
        Field(
            title="Image description",
            description="Human-readable description of Lab image",
            examples=[
                "Weekly 2026_08",
                "Experimental Release r29.2.0 (RSP Build 2629) [uajtpinlsdb]",
            ],
        ),
    ]

    image_digest: Annotated[
        str,
        Field(
            title="Digest of Lab image",
            description="Digest (should be unique) for a Lab image",
            examples=[
                (
                    "3a370098597c43ad518c6ab57c1e39d42ea369799"
                    "cc6a516770a0f9b30130223"
                )
            ],
        ),
    ]

    jupyter_image_spec: Annotated[
        str,
        Field(
            title="Image specification",
            description="Complete docker pull specification of Lab image",
            examples=[
                (
                    "us-central1-docker.pkg.dev/rubin-shared-services-71ec/"
                    "sciplat/sciplat-lab:exp_r29_2_0_rsp2629_uajtpinlsdb"
                    "@sha256:3a370098597c43ad518c6ab57c1e39d42"
                    "ea369799cc6a516770a0f9b30130223"
                )
            ],
        ),
    ]

    mem_guarantee: Annotated[
        int | str,
        Field(
            title="Memory guarantee (bytes)",
            description="Amount of memory guaranteed for Lab, in bytes",
            examples=[2e9, 1073741824, "8Gi"],
        ),
        BeforeValidator(memory_to_bytes),
    ]

    mem_limit: Annotated[
        int | str,
        Field(
            title="Memory limit (bytes)",
            description="Maximum amount of memory usable by Lab, in bytes",
            examples=[2e9, 1073741824, "8Gi"],
        ),
        BeforeValidator(memory_to_bytes),
    ]

    reset_user_env: Annotated[
        bool,
        Field(
            title="Reset user environment",
            description="Whether to reset user environment at startup",
        ),
    ] = False

    @field_validator("file_browser_root", mode="before")
    @classmethod
    def _validate_file_browser_root(cls, v: str) -> str:
        vals = [x.value for x in LabFileBrowserRoot]
        if v in vals:
            return v
        raise ValueError(f"Invalid file browser root value {v}")

    @field_validator("homedir_schema", mode="before")
    @classmethod
    def _validate_homedir_schema(cls, v: str) -> str:
        vals = [x.value for x in UserHomeDirectorySchema]
        if v in vals:
            return v
        raise ValueError(f"Invalid homedir schema value {v}")
