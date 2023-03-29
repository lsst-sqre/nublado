"""Tests for the REST spawner class."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from rsp_restspawner.errors import SpawnFailedError
from rsp_restspawner.spawner import LabStatus, RSPRestSpawner

from .support.controller import MockLabController


async def collect_progress(
    spawner: RSPRestSpawner,
) -> list[dict[str, int | str]]:
    """Gather progress from a spawner and return it as a list when done."""
    result = []
    async for message in spawner.progress():
        result.append(message)
    return result


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
    user = spawner.user.name
    expected = [
        {"progress": 2, "message": "[info] Lab creation initiated"},
        {"progress": 45, "message": "[info] Pod requested"},
        {
            "progress": 90,
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
    spawner: RSPRestSpawner, mock_lab_controller: MockLabController
) -> None:
    """Test multiple progress listeners for the same spawn."""
    mock_lab_controller.delay = timedelta(milliseconds=750)
    user = spawner.user.name
    expected = [
        {"progress": 2, "message": "[info] Lab creation initiated"},
        {"progress": 45, "message": "[info] Pod requested"},
        {
            "progress": 90,
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
    spawner: RSPRestSpawner, mock_lab_controller: MockLabController
) -> None:
    """Test error handling when a spawn fails."""
    mock_lab_controller.delay = timedelta(milliseconds=750)
    mock_lab_controller.fail_during_spawn = True
    user = spawner.user.name
    expected = [
        {"progress": 2, "message": "[info] Lab creation initiated"},
        {"progress": 45, "message": "[info] Pod requested"},
        {"progress": 45, "message": "[error] Something is going wrong"},
        {
            "progress": 45,
            "message": f"[error] Some random failure for {user}",
        },
        {
            "progress": 45,
            "message": "[warning] Lab creation failed, attempting to clean up",
        },
    ]

    results = await asyncio.gather(
        spawner.start(), collect_progress(spawner), return_exceptions=True
    )
    assert isinstance(results[0], SpawnFailedError)
    assert results[1] == expected

    # Because the spawn failed, we should have tried to shut down the lab. It
    # therefore should not exist, rather than hanging around in a failed
    # state.
    assert await spawner.poll() == 0
