"""Construct the spawner form."""

from __future__ import annotations

from jinja2 import Template
from structlog.stdlib import BoundLogger

from ..config import LabSizeDefinition
from ..constants import DROPDOWN_SENTINEL_VALUE, SPAWNER_FORM_TEMPLATE
from ..models.domain.form import FormSize
from ..models.v1.lab import LabSize
from .image import ImageService

__all__ = ["FormManager"]


class FormManager:
    """Service to construct the spawner form.

    Parameters
    ----------
    image_service
        Image service.
    lab_sizes
        Configured lab sizes.
    logger
        Logger to use.
    """

    def __init__(
        self,
        image_service: ImageService,
        lab_sizes: dict[LabSize, LabSizeDefinition],
        logger: BoundLogger,
    ) -> None:
        self._image_service = image_service
        self._logger = logger
        self._lab_sizes = lab_sizes

    def generate_user_lab_form(self) -> str:
        """Generate the spawner form in HTML."""
        options_template = Template(SPAWNER_FORM_TEMPLATE)
        images = self._image_service.menu_images()
        sizes = self._extract_sizes()
        return options_template.render(
            dropdown_sentinel=DROPDOWN_SENTINEL_VALUE,
            cached_images=images.menu,
            all_images=images.dropdown,
            sizes=sizes,
        )

    def _extract_sizes(self) -> list[FormSize]:
        """Create the lab sizes used in the spawner form."""
        sz = self._lab_sizes
        szlist = [
            FormSize(
                name=x.value.title(),
                cpu=str((sz[x]).cpu),
                memory=str((sz[x]).memory),
            )
            for x in sz
        ]
        szlist.reverse()
        return szlist
