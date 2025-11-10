"""Models used in the Nublado client public API."""

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import Annotated, Any, Literal, override

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CodeContext",
    "NotebookExecutionError",
    "NotebookExecutionResult",
    "NubladoImage",
    "NubladoImageByClass",
    "NubladoImageByReference",
    "NubladoImageByTag",
    "NubladoImageClass",
    "NubladoImageSize",
    "SpawnProgressMessage",
]


@dataclass
class CodeContext:
    """Optional context for exception reporting during code execution.

    This class can be passed into some `~rubin.nublado.client.NubladoClient`
    methods and will be used to annotate any raised exceptions with any
    available context information.
    """

    node: str | None = None
    """Name of the node on which the JupyterLab is running."""

    image: str | None = None
    """Docker image used for JupyterLab."""

    notebook: str | None = None
    """Name of the notebook."""

    cell: str | None = None
    """Identifier of notebook cell (usually a UUID)."""

    cell_number: str | None = None
    """Number of the notebook cell."""


class NotebookExecutionError(BaseModel):
    """An error from the notebook execution extension endpoint."""

    model_config = ConfigDict(validate_by_name=True)

    name: Annotated[str, Field(title="Error name", alias="ename")]

    value: Annotated[str, Field(title="Error value", alias="evalue")]

    message: Annotated[str, Field(title="Error message", alias="err_msg")]

    traceback: Annotated[str, Field(title="Exeception traceback")]


class NotebookExecutionResult(BaseModel):
    """Result from the notebook execution extension endpoint."""

    notebook: Annotated[
        str,
        Field(
            title="Notebook executed",
            description="Notebook that was executed, as a JSON string",
        ),
    ]

    resources: Annotated[
        dict[str, Any],
        Field(
            title="Resource output",
            description=(
                "Additional resources output by the notebook, as a JSON string"
            ),
        ),
    ] = {}

    error: Annotated[
        NotebookExecutionError | None,
        Field(
            title="Execution error",
            description="Will be None if no error occurred",
        ),
    ] = None


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

    model_config = ConfigDict(extra="forbid", validate_by_name=True)

    image_class: NubladoImageClass = Field(
        ..., title="Image class", alias="class"
    )

    size: NubladoImageSize = Field(
        NubladoImageSize.Large,
        title="Image size",
        description="Keyword selecting one of the Nublado image sizes",
    )

    debug: bool = Field(False, title="Whether to enable lab debugging")

    def to_logging_context(self) -> dict[str, str | bool]:
        """Convert to structured data to include the lab spawn log message.

        Returns
        -------
        dict of str
            Logging context intended to be passed to structlog.
        """
        return {
            "debug": self.debug,
            "image_class": self.image_class.value,
            "size": self.size.value.lower(),
        }

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
        NubladoImageClass.BY_REFERENCE, title="Image class", alias="class"
    )

    reference: str = Field(..., title="Docker reference of image")

    @override
    def to_logging_context(self) -> dict[str, str | bool]:
        result = super().to_logging_context()
        result["image"] = self.reference
        return result

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
        NubladoImageClass.BY_TAG, title="Image class", alias="class"
    )

    tag: str = Field(..., title="Image tag")

    @override
    def to_logging_context(self) -> dict[str, str | bool]:
        result = super().to_logging_context()
        result["image_tag"] = self.tag
        return result

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
        NubladoImageClass.RECOMMENDED, title="Image class", alias="class"
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


@dataclass(frozen=True, slots=True)
class SpawnProgressMessage:
    """A progress message from lab spawning."""

    progress: int
    """Percentage progress on spawning."""

    message: str
    """A progress message."""

    ready: bool
    """Whether the server is ready."""
