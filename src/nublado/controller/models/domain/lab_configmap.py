"""Model for sanitized configuration passed to Lab as mounted ConfigMap."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

from ...config import LabFileBrowserRoot, LabResources, SharedLabConfig

__all__ = ["LabConfigImageSettings", "LabConfigMap"]


class LabConfigImageSettings(BaseModel):
    """Settings describing the Lab container image."""

    description: Annotated[
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

    digest: Annotated[
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

    spec: Annotated[
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


class LabConfigMap(SharedLabConfig):
    """Items to pass to the Lab at startup as mounted ConfigMap.

    Some of these items come from the SharedLabConfig; others are included
    from different sources.
    """

    container_size: Annotated[
        str,
        Field(
            title="Container size",
            description="Human-readable container size",
            examples=["Large (4.0 CPU, 16Gi RAM)"],
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
        LabFileBrowserRoot,
        Field(
            title="JupyterLab file browser root",
            description=(
                "Whether to allow traversal in the UI file browser all"
                " the way up to the container root, or only as high as"
                " the user home directory."
            ),
        ),
    ] = LabFileBrowserRoot.HOME

    home_relative_to_file_browser_root: Annotated[
        str,
        Field(
            title="User home dir, relative to file browser root",
            description=(
                "The traversal path from the file browser root to the user's"
                " home directory."
            ),
        ),
    ] = ""

    image: Annotated[
        LabConfigImageSettings,
        Field(
            title="Lab image settings",
            description="Image settings for the Lab container.",
        ),
    ]

    reset_user_env: Annotated[
        bool,
        Field(
            title="Reset user environment",
            description="Whether to reset user environment at startup",
        ),
    ] = False

    resources: Annotated[
        LabResources,
        Field(
            title="Lab resources",
            description="CPU and memory requests and limits for Lab",
        ),
    ]
