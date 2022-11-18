"""Models for jupyterlab-controller."""

from pydantic import Field
from safir.metadata import Metadata as SafirMetadata

from .camelcase import CamelCaseModel


class Index(CamelCaseModel):
    """Metadata returned by the external root URL of the application.

    Notes
    -----
    As written, this is not very useful. Add additional metadata that will be
    helpful for a user exploring the application, or replace this model with
    some other model that makes more sense to return from the application API
    root.
    """

    metadata: SafirMetadata = Field(..., title="Package metadata")
