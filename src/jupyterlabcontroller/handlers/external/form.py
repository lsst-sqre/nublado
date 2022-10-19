from collections import defaultdict
from typing import Dict, List, Tuple

from fastapi import Depends, Request
from jinja2 import Template
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ...models.imageinfo import ImageInfo
from ...runtime.token import get_user_from_token
from .router import external_router

__all__ = ["get_user_lab_form"]


DROPDOWN_SENTINEL_VALUE = "use_image_from_dropdown"


def default_form_template() -> str:
    return "options_form.template"


group_to_form_map: Dict[str, str] = defaultdict(default_form_template)


def form_for_group(group: str) -> str:
    return f"../../static/{group_to_form_map[group]}"


@external_router.get(
    "/spawner/v1/lab-form/{username}",
    summary="Get lab form for user",
)
async def get_user_lab_form(
    request: Request,
    logger: BoundLogger = Depends(logger_dependency),
) -> str:
    """Requires exec:notebook and valid token."""
    token = request.headers.get("X-Auth-Request-Token")
    user = await get_user_from_token(token)
    username = user.username
    logger.info(f"Creating options form for '{username}'")
    dfl_form = form_for_group("")
    for grp in user.groups:
        form = form_for_group(grp.name)
        if form != dfl_form:
            # Take the first non-default form we find
            break
    with open(form) as f:
        template_str = f.read()
    options_template = Template(template_str)
    cached_images, all_images = _get_images()
    return options_template.render(
        dropdown_sentinel=DROPDOWN_SENTINEL_VALUE,
        cached_images=cached_images,
        all_images=all_images,
        sizes=[],
    )


def _get_images() -> Tuple[List[ImageInfo], List[ImageInfo]]:
    return ([], [])
