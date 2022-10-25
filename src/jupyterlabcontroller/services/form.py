from typing import Any, Dict, List, Tuple

from fastapi import Depends
from jinja2 import Template
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ...models.v1.external.imageinfo import ImageInfo
from ...models.v1.external.userdata import UserInfo
from ..runtime.config import form_config, lab_config

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


def generate_user_lab_form(
    user: UserInfo, logger: BoundLogger = Depends(logger_dependency)
) -> str:
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
