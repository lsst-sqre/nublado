from dataclasses import dataclass
from typing import List

from jinja2 import Template

from ..models.context import Context
from ..models.domain.form import FormSize
from .prepuller import PrepullerManager

DROPDOWN_SENTINEL_VALUE = "use_image_from_dropdown"


@dataclass
class FormManager:
    context: Context

    def form_for_group(self, group: str) -> str:
        return self.context.config.form.forms.get(
            group, self.context.config.form.forms["default"]
        )

    def _extract_sizes(self) -> List[FormSize]:
        sz = self.context.config.lab.sizes
        return [
            FormSize(
                name=x.title(),
                cpu=str((sz[x]).cpu),
                memory=str((sz[x]).memory),
            )
            for x in sz
        ]

    async def generate_user_lab_form(self) -> str:
        assert (
            self.context.user is not None
        ), "Cannot create user form without user"
        username = self.context.user.username
        self.context.logger.info(f"Creating options form for '{username}'")
        dfl_form = self.form_for_group("")
        for grp in self.context.user.groups:
            form = self.form_for_group(grp.name)
            if form != dfl_form:
                # Use first non-default form we encounter
                break
        options_template = Template(form)

        pm = PrepullerManager(context=self.context)
        displayimages = await pm.get_menu_images()
        cached_images = [displayimages[x] for x in displayimages if x != "all"]
        assert type(displayimages["all"]) is dict
        all_images = [displayimages["all"][x] for x in displayimages["all"]]
        sizes = self._extract_sizes()
        self.context.logger.debug(f"cached images: {cached_images}")
        self.context.logger.debug(f"all images: {all_images}")
        self.context.logger.debug(f"sizes: {sizes}")
        return options_template.render(
            dropdown_sentinel=DROPDOWN_SENTINEL_VALUE,
            cached_images=cached_images,
            all_images=all_images,
            sizes=sizes,
        )
