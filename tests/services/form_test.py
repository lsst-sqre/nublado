import pytest
from httpx import AsyncClient
from structlog.stdlib import BoundLogger

from jupyterlabcontroller.config import Configuration
from jupyterlabcontroller.services.form import FormManager
from jupyterlabcontroller.services.prepuller import PrepullerManager


@pytest.mark.asyncio
async def test_generate_user_lab_form(
    config: Configuration,
    prepuller_manager: PrepullerManager,
    logger: BoundLogger,
    http_client: AsyncClient,
) -> None:
    lab_sizes = config.lab.sizes
    fm: FormManager = FormManager(
        prepuller_manager=prepuller_manager,
        logger=logger,
        http_client=http_client,
        lab_sizes=lab_sizes,
    )
    r = await fm.generate_user_lab_form()
    assert (
        r.find(
            '<option value="lighthouse.ceres/library/sketchbook:'
            'recommended@sha256:5678">'
        )
        != -1
    )
