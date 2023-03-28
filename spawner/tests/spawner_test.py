import pytest

from rsp_restspawner.constants import LabStatus
from rsp_restspawner.spawner import RSPRestSpawner

from .support.controller import MockLabController


@pytest.mark.asyncio
async def test_start(spawner: RSPRestSpawner) -> None:
    user = spawner.user.name
    assert await spawner.start() == f"http://lab.nublado-{user}:8888"

    # Calling start again while it is running will return a 409, but then the
    # status endpoint should return the existing running lab, resulting in the
    # same apparent behavior.
    assert await spawner.start() == f"http://lab.nublado-{user}:8888"


@pytest.mark.asyncio
async def test_stop(spawner: RSPRestSpawner) -> None:
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
    spawner: RSPRestSpawner, mock_lab_controller: MockLabController
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


@pytest.mark.asyncio
async def test_options_form(spawner: RSPRestSpawner) -> None:
    expected = f"<p>This is some lab form for {spawner.user.name}</p>"
    assert await spawner.options_form(spawner) == expected


@pytest.mark.asyncio
async def test_progress(spawner: RSPRestSpawner) -> None:
    await spawner.start()
    expected = [
        {"progress": 2, "message": "Lab creation initiated", "ready": False},
        {"progress": 45, "message": "Pod requested", "ready": False},
        {
            "progress": 90,
            "message": f"Pod successfully spawned for {spawner.user.name}",
            "ready": True,
        },
    ]
    index = 0
    async for message in spawner.progress():
        assert message == expected[index]
        index += 1
    assert index == len(expected)
