"""Test features of the Jupyter mock for the Nublado client."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from rubin.nublado.client import (
    MockJupyter,
    NubladoClient,
    NubladoExecutionError,
    NubladoImageByClass,
    NubladoWebError,
)


@pytest.mark.asyncio
async def test_order(client: NubladoClient) -> None:
    """Test that the Jupyter mock enforces order of operations."""
    with pytest.raises(AssertionError):
        await client.spawn_lab(NubladoImageByClass())
    with pytest.raises(AssertionError):
        await client.wait_for_spawn()
    with pytest.raises((AssertionError, NubladoWebError)):
        await client.auth_to_lab()
    with pytest.raises((AssertionError, NubladoWebError)):
        await client.run_notebook("")
    with pytest.raises((AssertionError, NubladoWebError)):
        async with client.lab_session():
            pass

    await client.auth_to_hub()
    with pytest.raises(AssertionError):
        await client.wait_for_spawn()
    with pytest.raises((AssertionError, NubladoWebError)):
        await client.auth_to_lab()
    with pytest.raises((AssertionError, NubladoWebError)):
        await client.run_notebook("")
    with pytest.raises((AssertionError, NubladoWebError)):
        async with client.lab_session():
            pass

    await client.spawn_lab(NubladoImageByClass())
    with pytest.raises((AssertionError, NubladoWebError)):
        await client.auth_to_lab()
    with pytest.raises((AssertionError, NubladoWebError)):
        await client.run_notebook("")
    with pytest.raises((AssertionError, NubladoWebError)):
        async with client.lab_session():
            pass

    await client.wait_for_spawn()
    with pytest.raises(AssertionError):
        await client.spawn_lab(NubladoImageByClass())
    async with client.lab_session():
        pass

    await client.stop_lab()
    with pytest.raises(AssertionError):
        await client.wait_for_spawn()
    with pytest.raises((AssertionError, NubladoWebError)):
        await client.auth_to_lab()
    with pytest.raises((AssertionError, NubladoWebError)):
        await client.run_notebook("")
    with pytest.raises((AssertionError, NubladoWebError)):
        async with client.lab_session():
            pass


@pytest.mark.asyncio
async def test_register_python_result(
    client: NubladoClient, mock_jupyter: MockJupyter
) -> None:
    code = "What do you get when you multiply six by nine?"
    mock_jupyter.register_python_result(code, "42")
    mock_jupyter.register_python_result("blah", ValueError("some error"))

    await client.auth_to_hub()
    await client.spawn_lab(NubladoImageByClass())
    await client.wait_for_spawn()
    await client.auth_to_lab()
    async with client.lab_session() as session:
        with pytest.raises(NubladoExecutionError) as exc_info:
            await session.run_python("blah")
        assert "ValueError: some error" in str(exc_info.value)
        assert await session.run_python(code) == "42"


@pytest.mark.asyncio
async def test_set_spawn_delay(
    client: NubladoClient, mock_jupyter: MockJupyter
) -> None:
    mock_jupyter.set_spawn_delay(timedelta(seconds=0.5))

    await client.auth_to_hub()
    await client.spawn_lab(NubladoImageByClass())
    start = datetime.now(tz=UTC)
    await client.wait_for_spawn()
    assert datetime.now(tz=UTC) - start >= timedelta(seconds=0.5)


@pytest.mark.asyncio
async def test_set_delete_delay(
    client: NubladoClient, mock_jupyter: MockJupyter
) -> None:
    mock_jupyter.set_delete_delay(timedelta(seconds=0.5))

    await client.auth_to_hub()
    await client.spawn_lab(NubladoImageByClass())
    await client.wait_for_spawn()
    assert not await client.is_lab_stopped()
    await client.stop_lab()
    assert not await client.is_lab_stopped()
    with pytest.raises(AssertionError):
        await client.spawn_lab(NubladoImageByClass())
    await asyncio.sleep(0.5)
    assert await client.is_lab_stopped()
    await client.spawn_lab(NubladoImageByClass())
    await client.wait_for_spawn()
