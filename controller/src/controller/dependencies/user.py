"""User and authentication dependencies for FastAPI."""

from typing import Annotated

from fastapi import Depends, Header, Path

from ..exceptions import PermissionDeniedError
from ..models.domain.gafaelfawr import GafaelfawrUser
from .context import RequestContext, context_dependency

__all__ = [
    "user_dependency",
    "username_path_dependency",
]


async def user_dependency(
    context: Annotated[RequestContext, Depends(context_dependency)],
    x_auth_request_user: Annotated[str, Header(include_in_schema=False)],
    x_auth_request_token: Annotated[str, Header(include_in_schema=False)],
) -> GafaelfawrUser:
    """Return the validated user for the given request.

    Some user routes will have both a user token and a user name specified in
    the headers. We want to make sure that the user name matches the name of
    the user that owns the token.

    Returns
    -------
    GafaelfawrUser
        Validated user metadata from Gafaelfawr.

    Raises
    ------
    controller.exceptions.GafaelfawrParseError
        Raised if the Gafaelfawr response could not be parsed.
    controller.exceptions.GafaelfawrWebError
        Raised if the token could not be validated with Gafaelfawr.
    controller.exceptions.InvalidTokenError
        Raised if the token was rejected by Gafaelfawr.
    PermissionDeniedError
        Raised if the user's token does not match the username in the header.
    """
    gafaelfawr_client = context.factory.create_gafaelfawr_client()
    user = await gafaelfawr_client.get_user_info(x_auth_request_token)
    if user.username != x_auth_request_user:
        raise PermissionDeniedError("Permission denied")
    context.rebind_logger(user=user.username)
    return GafaelfawrUser(token=x_auth_request_token, **user.model_dump())


async def username_path_dependency(
    username: Annotated[str, Path()],
    x_auth_request_user: Annotated[str, Header(include_in_schema=False)],
) -> str:
    """Validate and return the username in the request path.

    Some routes take the uesrname in the request path and require the
    authenticated user match that username. This dependency performs that
    check.

    Returns
    -------
    str
        Validated username.

    Raises
    ------
    PermissionDeniedError
        Raised if the username in the header added by Gafaelfawr doesn't match
        the username in the path.
    """
    if username != x_auth_request_user:
        raise PermissionDeniedError("Permission denied")
    return username
