from typing import List, Tuple

from jinja2 import Template
from structlog.stdlib import BoundLogger

from ..models.v1.domain.config import Config
from ..models.v1.external.prepuller import Image
from ..models.v1.external.userdata import UserInfo

DROPDOWN_SENTINEL_VALUE = "use_image_from_dropdown"


class FormManager:
    def __init__(
        self, config: Config, user: UserInfo, logger: BoundLogger
    ) -> None:
        self.config = config
        self.user = user
        self.logger = logger

    def form_for_group(self, group: str) -> str:
        return self.config.form.forms.get(
            group, self.config.form.forms["default"]
        )

    def _get_images(self) -> Tuple[List[UserInfo], List[Image]]:
        # TODO: ask the prepuller for its cache, and use that.
        return ([], [])

    def _extract_sizes(self) -> List[str]:
        sz = self.config.lab.sizes
        return [
            f"{x.title()} ({(sz[x]).cpu} CPU, {(sz[x]).memory} memory."
            for x in sz
        ]

    def generate_user_lab_form(self) -> str:
        username = self.user.username
        self.logger.info(f"Creating options form for '{username}'")
        dfl_form = self.form_for_group("")
        for grp in self.user.groups:
            form = self.form_for_group(grp.name)
            if form != dfl_form:
                # Use first non-default form we encounter
                break
        options_template = Template(form)
        cached_images, all_images = self._get_images()
        sizes = self._extract_sizes()
        return options_template.render(
            dropdown_sentinel=DROPDOWN_SENTINEL_VALUE,
            cached_images=cached_images,
            all_images=all_images,
            sizes=sizes,
        )
