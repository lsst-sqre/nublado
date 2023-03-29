from jinja2 import Template
from structlog.stdlib import BoundLogger

from ..config import LabSizeDefinition
from ..constants import DROPDOWN_SENTINEL_VALUE, SPAWNER_FORM_TEMPLATE
from ..models.domain.form import FormSize
from ..models.v1.lab import LabSize
from .image import ImageService


class FormManager:
    def __init__(
        self,
        image_service: ImageService,
        lab_sizes: dict[LabSize, LabSizeDefinition],
        logger: BoundLogger,
    ):
        self._image_service = image_service
        self._logger = logger
        self._lab_sizes = lab_sizes

    def generate_user_lab_form(self) -> str:
        options_template = Template(SPAWNER_FORM_TEMPLATE)
        images = self._image_service.menu_images()
        sizes = self._extract_sizes()
        rendered = options_template.render(
            dropdown_sentinel=DROPDOWN_SENTINEL_VALUE,
            cached_images=images.menu,
            all_images=images.dropdown,
            sizes=sizes,
        )
        return rendered

    def _extract_sizes(self) -> list[FormSize]:
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
