from typing import Any, Dict, List, Tuple

from fastapi import Depends, Request
from jinja2 import Template
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ...models.v1.external.imageinfo import ImageInfo
from ...runtime.config import form_config, lab_config
from ...runtime.token import get_user_from_token
from .router import external_router

__all__ = ["get_user_lab_form"]


DROPDOWN_SENTINEL_VALUE = "use_image_from_dropdown"


def form_for_group(group: str) -> str:
    forms_dict = form_config["forms"]
    return forms_dict.get(group, forms_dict["default"])


def _get_images() -> Tuple[List[ImageInfo], List[ImageInfo]]:
    # TODO: ask the prepuller for its cache, and use that.
    return ([], [])


def _extract_sizes(cfg: Dict[str, Any]) -> List[str]:
    sz: Dict[str, Any] = cfg["sizes"]
    return [
        f"{x.title()} ({sz[x]['cpu']} CPU, {sz[x]['memory']} memory."
        for x in sz
    ]


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
            # Use first non-default form we encounter
            break
    options_template = Template(form)
    cached_images, all_images = _get_images()
    sizes = _extract_sizes(lab_config)
    return options_template.render(
        dropdown_sentinel=DROPDOWN_SENTINEL_VALUE,
        cached_images=cached_images,
        all_images=all_images,
        sizes=sizes,
    )
