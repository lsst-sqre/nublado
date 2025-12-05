"""Route handler for user file server creation.

This router manages the route used by the user to create file servers. Unlike
the administrative routes (in `controller.handlers.fileserver`), this route is
not mounted under the general path prefix for the controller. It is instead
mounted under the ``fileserver.path_prefix`` setting in the Nublado controller
configuration. Normally, this is ``/files``.

All requests for this route **and anything under this route** are directed to
this route by the Kubernetes ``Ingress``. Specifically, this means that both
``/files`` and :samp:`/files/{username}` (assuming the default path prefix)
are sent to this route if there is no more specific ingress.

When the user file server is created, it gets an accompanying ``Ingress``
resource specific to that user (:samp:`/files/{username}`). Since that match
is longer than the ``/files`` match in the general ``Ingress``, traffic for
that user is then sent to their file server instead of to this route. When
that file server times out and is deleted, the ``Ingress`` is also deleted,
and the catch-all ``Ingress`` once again sends the user to this route, where a
new file server will be spawned.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, Response
from safir.models import ErrorModel
from safir.slack.webhook import SlackRouteErrorHandler

from ..config import Config
from ..dependencies.config import config_dependency
from ..dependencies.context import RequestContext, context_dependency
from ..dependencies.user import user_dependency
from ..exceptions import NotConfiguredError
from ..models.domain.gafaelfawr import GafaelfawrUser
from ..templates import templates

router = APIRouter(route_class=SlackRouteErrorHandler)
"""Router to mount into the application."""

__all__ = ["router"]


@router.get(
    "",
    summary="Create file server for user",
    responses={403: {"description": "Forbidden", "model": ErrorModel}},
    response_class=HTMLResponse,
    tags=["user"],
)
async def route_user(
    context: Annotated[RequestContext, Depends(context_dependency)],
    config: Annotated[Config, Depends(config_dependency)],
    user: Annotated[GafaelfawrUser, Depends(user_dependency)],
) -> Response:
    context.rebind_logger(user=user.username)
    if not config.fileserver.enabled:
        raise NotConfiguredError("Fileserver is disabled in configuration")

    # Spawn the file server if necessary.
    try:
        await context.fileserver_manager.create(user)
    except Exception as e:
        # The exception (other than timeout errors) was already reported to
        # Slack at the service layer, so convert it to a standard error
        # message instead of letting it propagate as an uncaught exception.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=[
                {
                    "msg": f"Failed to create file server: {e!s}",
                    "type": "file_server_create_failed",
                }
            ],
        ) from e

    # Construct and return the instructions page.
    return templates.TemplateResponse(
        context.request,
        "fileserver.html.jinja",
        {
            "username": user.username,
            "base_url": config.base_url,
            "path_prefix": config.fileserver.path_prefix,
            "timeout": config.fileserver.idle_timeout,
        },
    )
