"""Routes for generating spawner forms."""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, Response
from safir.models import ErrorModel
from safir.slack.webhook import SlackRouteErrorHandler

from ..config import Config
from ..constants import DROPDOWN_SENTINEL_VALUE
from ..dependencies.config import config_dependency
from ..dependencies.context import RequestContext, context_dependency
from ..dependencies.user import user_dependency
from ..exceptions import PermissionDeniedError
from ..models.domain.gafaelfawr import GafaelfawrUser
from ..templates import templates

router = APIRouter(route_class=SlackRouteErrorHandler)
"""Router to mount into the application."""

__all__ = ["router"]


@router.get(
    "/spawner/v1/lab-form/{username}",
    summary="Get lab form for user",
    response_class=HTMLResponse,
    responses={403: {"description": "Forbidden", "model": ErrorModel}},
    tags=["user"],
)
async def get_user_lab_form(
    username: str,
    user: Annotated[GafaelfawrUser, Depends(user_dependency)],
    config: Annotated[Config, Depends(config_dependency)],
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> Response:
    if username != user.username:
        raise PermissionDeniedError("Permission denied")
    images = context.image_service.menu_images()

    # Filter the list of configured lab sizes to exclude labs that are larger
    # than the user's quota, if they have a quota. Also handle the case where
    # the user's quota says they cannot spawn labs at all.
    if user.quota and user.quota.notebook:
        quota = user.quota.notebook
        sizes = [
            s
            for s in config.lab.sizes
            if s.resources.limits.memory <= quota.memory_bytes
            and s.resources.limits.cpu <= quota.cpu
        ]
        if not sizes or not quota.spawn:
            return templates.TemplateResponse(
                context.request, "unavailable.html.jinja"
            )
    else:
        sizes = config.lab.sizes

    # Determine the default size.
    default_size = None
    if config.lab.default_size:
        for size in sizes:
            if size.size == config.lab.default_size:
                default_size = config.lab.default_size
                break
    if not default_size:
        default_size = sizes[0].size

    # Construct and return the spawner form.
    return templates.TemplateResponse(
        context.request,
        "spawner.html.jinja",
        {
            "dropdown_sentinel": DROPDOWN_SENTINEL_VALUE,
            "cached_images": images.menu,
            "all_images": images.dropdown,
            "sizes": sizes,
            "default_size": default_size,
        },
    )
