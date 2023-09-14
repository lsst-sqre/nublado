"""User dependency for FastAPI.

Some user routes will have both a user token and a user name specified
in the headers.

We want to make sure that the user name matches the name of the user
that owns the token.  If so, return a UserInfo record for the user,
with the token filled in.  If not, raise an error.
"""

from fastapi import Depends, Header, Request

from ..exceptions import PermissionDeniedError
from ..models.domain.gafaelfawr import GafaelfawrUser
from .context import RequestContext, context_dependency

__all__ = ["UserDependency", "user_dependency"]


class UserDependency:
    """Obtain user metadata from a Gafaelfawr token in the request.

    Provides a `~jupyterlabcontroller.models.domain.gafaelfawr.GafaelfawrUser`
    structure with the user details, including the token used to procure that
    structure from Gafaelfawr.
    """

    async def __call__(
        self,
        request: Request,
        context: RequestContext = Depends(context_dependency),
        x_auth_request_user: str = Header(..., include_in_schema=False),
        x_auth_request_token: str = Header(..., include_in_schema=False),
    ) -> GafaelfawrUser:
        """Return a logger bound with request information.

        Returns
        -------
        GafaelfawrUser
            The matching user
        """
        gafaelfawr_client = context.factory.create_gafaelfawr_client()
        user = await gafaelfawr_client.get_user_info(x_auth_request_token)
        if user.username != x_auth_request_user:
            raise PermissionDeniedError("Permission denied")
        context.rebind_logger(user=user.username)
        return GafaelfawrUser(token=x_auth_request_token, **user.model_dump())


user_dependency = UserDependency()
"""The dependency that will return the user for the current request."""
