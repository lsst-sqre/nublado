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
from ..exceptions import InsufficientQuotaError, PermissionDeniedError
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
    # than the user's quota, if they have a quota.
    if user.quota and user.quota.notebook:
        quota = user.quota.notebook
        sizes = [
            s
            for s in config.lab.sizes
            if s.memory_bytes <= quota.memory_bytes and s.cpu <= quota.cpu
        ]
        if not sizes:
            msg = "Insufficient quota to spawn smallest lab"
            raise InsufficientQuotaError(msg)
    else:
        sizes = config.lab.sizes

    # Construct and return the spawner form.
    return templates.TemplateResponse(
        context.request,
        "spawner.html.jinja",
        {
            "dropdown_sentinel": DROPDOWN_SENTINEL_VALUE,
            "cached_images": images.menu,
            "all_images": images.dropdown,
            "sizes": sizes,
        },
    )
