"""Models for talking to Gafaelfawr."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field
from rubin.gafaelfawr import GafaelfawrUserInfo

__all__ = ["GafaelfawrUser"]


class GafaelfawrUser(GafaelfawrUserInfo):
    """User information from Gafaelfawr supplemented with the user's token.

    This model is used to pass the user information around internally,
    bundling the user's metadata with their notebook token.
    """

    token: Annotated[str, Field(title="Notebook token")]
