"""User dependency for FastAPI.

Some user routes will have both a user token and a user name specified in the
headers. We want to make sure that the user name matches the name of the user
that owns the token. If so, return a
`~controller.models.domain.gafaelfawr.GafaelfawrUser` record for the user,
with the token filled in. If not, raise an error.
"""

from fastapi import Depends, Header, Request

from ..exceptions import PermissionDeniedError
from ..models.domain.gafaelfawr import GafaelfawrUser
from .context import RequestContext, context_dependency

__all__ = ["user_dependency"]


async def user_dependency(
    request: Request,
    context: RequestContext = Depends(context_dependency),
    x_auth_request_user: str = Header(..., include_in_schema=False),
    x_auth_request_token: str = Header(..., include_in_schema=False),
) -> GafaelfawrUser:
    """Return the validated user for the given request."""
    gafaelfawr_client = context.factory.create_gafaelfawr_client()
    user = await gafaelfawr_client.get_user_info(x_auth_request_token)
    if user.username != x_auth_request_user:
        raise PermissionDeniedError("Permission denied")
    context.rebind_logger(user=user.username)
    return GafaelfawrUser(token=x_auth_request_token, **user.model_dump())
