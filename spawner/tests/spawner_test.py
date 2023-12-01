"""Tests for the Nublado spawner class."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from rubin.nublado.spawner import NubladoSpawner
from rubin.nublado.spawner._exceptions import SpawnFailedError
from rubin.nublado.spawner._models import LabStatus

from .support.controller import MockLabController


async def collect_progress(
    spawner: NubladoSpawner,
) -> list[dict[str, int | str]]:
    """Gather progress from a spawner and return it as a list when done."""
    return [m async for m in spawner.progress()]


@pytest.mark.asyncio
async def test_start(spawner: NubladoSpawner) -> None:
    user = spawner.user.name
    assert await spawner.start() == f"http://lab.nublado-{user}:8888"

    # Calling start again while it is running will return a 409, which should
    # trigger deletion of the lab followed by its recreation. This turns into
    # the same apparent behavior at the API level. (The details of this are
    # tested later.)
    assert await spawner.start() == f"http://lab.nublado-{user}:8888"


@pytest.mark.asyncio
async def test_stop(spawner: NubladoSpawner) -> None:
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
    spawner: NubladoSpawner, mock_lab_controller: MockLabController
) -> None:
    assert await spawner.poll() == 0
    mock_lab_controller.set_status(spawner.user.name, LabStatus.PENDING)
    assert await spawner.poll() is None
    mock_lab_controller.set_status(spawner.user.name, LabStatus.RUNNING)
    assert await spawner.poll() is None
    mock_lab_controller.set_status(spawner.user.name, LabStatus.TERMINATING)
    assert await spawner.poll() == 0
    mock_lab_controller.set_status(spawner.user.name, LabStatus.TERMINATED)
    assert await spawner.poll() == 0
    mock_lab_controller.set_status(spawner.user.name, LabStatus.FAILED)
    assert await spawner.poll() == 1
    await spawner.stop()
    assert await spawner.poll() == 0


@pytest.mark.asyncio
async def test_get_url(spawner: NubladoSpawner) -> None:
    user = spawner.user.name
    assert await spawner.start() == f"http://lab.nublado-{user}:8888"
    assert await spawner.get_url() == f"http://lab.nublado-{user}:8888"


@pytest.mark.asyncio
async def test_options_form(spawner: NubladoSpawner) -> None:
    expected = f"<p>This is some lab form for {spawner.user.name}</p>"
    assert await spawner.options_form(spawner) == expected


@pytest.mark.asyncio
async def test_progress(spawner: NubladoSpawner) -> None:
    await spawner.start()
    user = spawner.user.name
    expected = [
        {"progress": 2, "message": "[info] Lab creation initiated"},
        {"progress": 45, "message": "[info] Pod requested"},
        {
            "progress": 75,
            "message": f"[info] Pod successfully spawned for {user}",
        },
    ]
    index = 0
    async for message in spawner.progress():
        assert message == expected[index]
        index += 1
    assert index == len(expected)


@pytest.mark.asyncio
async def test_progress_conflict(spawner: NubladoSpawner) -> None:
    await spawner.start()

    # Start it a second time, which should trigger deleting the old lab.
    await spawner.start()
    user = spawner.user.name
    expected = [
        {"progress": 1, "message": "[warning] Deleting existing orphaned lab"},
        {"progress": 2, "message": "[info] Lab creation initiated"},
        {"progress": 45, "message": "[info] Pod requested"},
        {
            "progress": 75,
            "message": f"[info] Pod successfully spawned for {user}",
        },
    ]
    index = 0
    async for message in spawner.progress():
        assert message == expected[index]
        index += 1
    assert index == len(expected)


@pytest.mark.asyncio
async def test_progress_multiple(
    spawner: NubladoSpawner, mock_lab_controller: MockLabController
) -> None:
    """Test multiple progress listeners for the same spawn."""
    mock_lab_controller.delay = timedelta(milliseconds=750)
    user = spawner.user.name
    expected = [
        {"progress": 2, "message": "[info] Lab creation initiated"},
        {"progress": 45, "message": "[info] Pod requested"},
        {
            "progress": 75,
            "message": f"[info] Pod successfully spawned for {user}",
        },
    ]

    results = await asyncio.gather(
        spawner.start(),
        collect_progress(spawner),
        collect_progress(spawner),
        collect_progress(spawner),
    )
    url = results[0]
    assert url == f"http://lab.nublado-{user}:8888"
    for events in results[1:]:
        assert events == expected


@pytest.mark.asyncio
async def test_spawn_failure(
    spawner: NubladoSpawner, mock_lab_controller: MockLabController
) -> None:
    """Test error handling when a spawn fails.

    Also tests invalid JSON in the event body. In those cases, the raw event
    body should be treated as the message.
    """
    mock_lab_controller.delay = timedelta(milliseconds=750)
    mock_lab_controller.fail_during_spawn = True
    user = spawner.user.name
    expected = [
        {"progress": 2, "message": "[info] Lab creation initiated"},
        {"progress": 45, "message": "[info] Pod requested"},
        {"progress": 45, "message": "[unknown] This is not JSON"},
        {"progress": 45, "message": "[error] Something is going wrong"},
        {"progress": 45, "message": '[info] {"invalid": "value"}'},
        {
            "progress": 45,
            "message": '[info] {"message": "Blah", "progress": "Happy!"}',
        },
        {
            "progress": 45,
            "message": f"[error] Some random failure for {user}",
        },
    ]

    results = await asyncio.gather(
        spawner.start(), collect_progress(spawner), return_exceptions=True
    )
    assert isinstance(results[0], SpawnFailedError)
    assert results[1] == expected
