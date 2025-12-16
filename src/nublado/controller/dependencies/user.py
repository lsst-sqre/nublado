"""User and authentication dependencies for FastAPI."""

from typing import Annotated

from fastapi import Depends, Header, Path
from rubin.gafaelfawr import GafaelfawrWebError

from ..exceptions import InvalidTokenError, PermissionDeniedError
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
    InvalidTokenError
        Raised if the user's token is invalid.
    PermissionDeniedError
        Raised if the user's token does not match the username in the header.
    rubin.gafaelfawr.GafaelfawrError
        Raised if user information could not be retrieved from Gafaelfawr.
    rubin.repertoire.RepertoireError
        Raised if Gafaelfawr could not be found in service discovery.
    """
    token = x_auth_request_token
    try:
        userinfo = await context.gafaelfawr_client.get_user_info(token)
    except GafaelfawrWebError as e:
        if e.status in (401, 403):
            raise InvalidTokenError("User token is invalid") from e
        raise
    if userinfo.username != x_auth_request_user:
        raise PermissionDeniedError("Permission denied")
    context.rebind_logger(user=userinfo.username)
    return GafaelfawrUser(token=token, **userinfo.model_dump())


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
