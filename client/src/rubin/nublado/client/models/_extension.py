"""Models for notebook execution via the ``/user/:username/rubin/execution``
extension endpoint.
"""

from typing import Annotated, Any

from pydantic import BaseModel, Field


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
