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
from ..dependencies.user import username_path_dependency
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
    username: Annotated[str, Depends(username_path_dependency)],
    config: Annotated[Config, Depends(config_dependency)],
    context: Annotated[RequestContext, Depends(context_dependency)],
) -> Response:
    images = context.image_service.menu_images()
    return templates.TemplateResponse(
        "spawner.html.jinja",
        {
            "request": context.request,
            "dropdown_sentinel": DROPDOWN_SENTINEL_VALUE,
            "cached_images": images.menu,
            "all_images": images.dropdown,
            "sizes": config.lab.sizes,
        },
    )
