from typing import List

from httpx import AsyncClient
from jinja2 import Template
from structlog.stdlib import BoundLogger

from ..config import LabSizeDefinitions
from ..constants import SPAWNER_FORM_TEMPLATE
from ..models.domain.form import FormSize
from .prepuller.arbitrator import PrepullerArbitrator

DROPDOWN_SENTINEL_VALUE = "use_image_from_dropdown"


class FormManager:
    def __init__(
        self,
        prepuller_arbitrator: PrepullerArbitrator,
        logger: BoundLogger,
        http_client: AsyncClient,
        lab_sizes: LabSizeDefinitions,
    ):
        self.prepuller_arbitrator = prepuller_arbitrator
        self.logger = logger
        self.http_client = http_client
        self.lab_sizes = lab_sizes

    def _extract_sizes(self) -> List[FormSize]:
        sz = self.lab_sizes
        return [
            FormSize(
                name=x.title(),
                cpu=str((sz[x]).cpu),
                memory=str((sz[x]).memory),
            )
            for x in sz
        ]

    def generate_user_lab_form(self) -> str:
        options_template = Template(SPAWNER_FORM_TEMPLATE)

        pa = self.prepuller_arbitrator
        displayimages = pa.get_menu_images()
        cached_images = list(displayimages.menu.values())
        all_images = list(displayimages.all.values())
        sizes = self._extract_sizes()
        return options_template.render(
            dropdown_sentinel=DROPDOWN_SENTINEL_VALUE,
            cached_images=cached_images,
            all_images=all_images,
            sizes=sizes,
        )
