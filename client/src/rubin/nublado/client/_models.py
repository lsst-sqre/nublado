"""Models used in the Nublado client public API."""

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import Annotated, Any, Literal, override

from pydantic import BaseModel, Field

__all__ = [
    "CodeContext",
    "JupyterOutput",
    "NotebookExecutionErrorModel",
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
    """Optional context for exception reporting during code execution."""

    image: str | None = None
    notebook: str | None = None
    path: str | None = None
    cell: str | None = None
    cell_number: str | None = None
    cell_source: str | None = None
    cell_line_number: str | None = None
    cell_line_source: str | None = None


class NotebookExecutionErrorModel(BaseModel):
    """The error from the ``/user/:username/rubin/execution`` endpoint."""

    traceback: Annotated[str, Field(description="The exeception traceback.")]

    ename: Annotated[str, Field(description="The exception name.")]

    evalue: Annotated[str, Field(description="The exception value.")]

    err_msg: Annotated[str, Field(description="The exception message.")]


class NotebookExecutionResult(BaseModel):
    """The result of the /user/:username/rubin/execution endpoint."""

    notebook: Annotated[
        str,
        Field(description="The notebook that was executed, as a JSON string."),
    ]

    resources: Annotated[
        dict[str, Any],
        Field(
            description=(
                "The resources used to execute the notebook, as a JSON string."
            )
        ),
    ]

    error: Annotated[
        NotebookExecutionErrorModel | None,
        Field(description="The error that occurred during execution."),
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

    # Ideally this would just be class, but it is a keyword and adding all the
    # plumbing to correctly serialize Pydantic models by alias instead of
    # field name is tedious and annoying. Live with the somewhat verbose name.
    image_class: NubladoImageClass = Field(
        ...,
        title="Class of image to spawn",
    )

    size: NubladoImageSize = Field(
        NubladoImageSize.Large,
        title="Size of image to spawn",
        description="Must be one of the sizes understood by Nublado.",
    )

    description: str = Field("", title="Human-readable image description")

    debug: bool = Field(False, title="Whether to enable lab debugging")

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
        NubladoImageClass.BY_REFERENCE, title="Class of image to spawn"
    )

    reference: str = Field(..., title="Docker reference of lab image to spawn")

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
        NubladoImageClass.BY_TAG, title="Class of image to spawn"
    )

    tag: str = Field(..., title="Tag of image to spawn")

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
        NubladoImageClass.RECOMMENDED,
        title="Class of image to spawn",
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
class JupyterOutput:
    """Output from a Jupyter lab kernel.

    Parsing WebSocket messages will result in a stream of these objects with
    partial output, ending in a final one with the ``done`` flag set.

    Note that there is some subtlety here: a notebook cell can either
    print its output (that is, write to stdout), or, in an executed notebook,
    the cell will display the last Python command run.

    These are currently represented by two unhandled message types,
    ``execute_result`` (which is the result of the last Python command run;
    this is analogous to what you get in the Pytheon REPL loop) and
    ``display_data``.  ``display_data`` would be what you get, for instance,
    when you ask Bokeh to show a figure: it's a bunch of Javascript that
    will be interpreted by your browser.

    The protocol is found at https://jupyter-client.readthedocs.io/en/latest/
    but what we want to use is half a layer above that.  We care what
    some messages on the various channels are, but not at all about the
    low-level implementation details of how those channels are established
    over ZMQ, for instance.
    """

    content: str
    """Partial output from code execution (may be empty)."""

    done: bool = False
    """Whether this indicates the end of execution."""


@dataclass(frozen=True, slots=True)
class SpawnProgressMessage:
    """A progress message from lab spawning."""

    progress: int
    """Percentage progress on spawning."""

    message: str
    """A progress message."""

    ready: bool
    """Whether the server is ready."""
