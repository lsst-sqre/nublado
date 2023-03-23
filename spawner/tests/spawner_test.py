import pytest
import respx

from rsp_restspawner.constants import LabStatus
from rsp_restspawner.spawner import RSPRestSpawner

from .support.controller import MockLabController


@pytest.mark.asyncio
async def test_start(
    respx_mock: respx.Router,
    spawner: RSPRestSpawner,
) -> None:
    user = spawner.user.name
    assert await spawner.start() == f"http://lab.nublado-{user}:8888"

    # Calling start again while it is running will return a 409, but then the
    # status endpoint should return the existing running lab, resulting in the
    # same apparent behavior.
    assert await spawner.start() == f"http://lab.nublado-{user}:8888"


@pytest.mark.asyncio
async def test_stop(respx_mock: respx.Router, spawner: RSPRestSpawner) -> None:
    user = spawner.user.name
    assert await spawner.start() == f"http://lab.nublado-{user}:8888"
    assert await spawner.poll() is None
    await spawner.stop()
    assert await spawner.poll() == 0

    # Delete a nonexistent lab. The lab controller will return 404, but the
    # spawner should swallow it.
    await spawner.stop()


@pytest.mark.asyncio
async def test_poll(
    respx_mock: respx.Router,
    spawner: RSPRestSpawner,
    mock_lab_controller: MockLabController,
) -> None:
    assert await spawner.poll() == 0
    mock_lab_controller.set_status(spawner.user.name, LabStatus.STARTING)
    assert await spawner.poll() is None
    mock_lab_controller.set_status(spawner.user.name, LabStatus.RUNNING)
    assert await spawner.poll() is None
    mock_lab_controller.set_status(spawner.user.name, LabStatus.TERMINATING)
    assert await spawner.poll() is None
    mock_lab_controller.set_status(spawner.user.name, LabStatus.FAILED)
    assert await spawner.poll() == 1
    await spawner.stop()
    assert await spawner.poll() == 0
