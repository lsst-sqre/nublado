"""Tests for the NubladoClient object."""

import asyncio
from pathlib import Path

import pytest

from rubin.nublado.client import NubladoClient
from rubin.nublado.client.models.image import (
    NubladoImageByClass,
    NubladoImageClass,
    NubladoImageSize,
)
from rubin.nublado.client.testing.jupyter import MockJupyter


@pytest.mark.asyncio
async def test_hub_flow(
    configured_client: NubladoClient, jupyter: MockJupyter
) -> None:
    try:
        assert await configured_client.is_lab_stopped()
        raise RuntimeError("Pre-auth lab check should have raised Exception")
    except AssertionError:
        pass
    await configured_client.auth_to_hub()
    assert await configured_client.is_lab_stopped()
    # Simulate spawn
    await configured_client.spawn_lab(
        NubladoImageByClass(
            image_class=NubladoImageClass.RECOMMENDED,
            size=NubladoImageSize.Medium,
        )
    )
    # Watch the progress meter
    progress = configured_client.watch_spawn_progress()
    progress_pct = -1
    async with asyncio.timeout(30):
        async for message in progress:
            if message.ready:
                break
            assert message.progress > progress_pct
            progress_pct = message.progress
    # Is the lab running?  Should be.
    assert not (await configured_client.is_lab_stopped())
    try:
        async with configured_client.open_lab_session() as lab_session:
            pass
        raise RuntimeError(
            "Pre-auth-to-lab session should have raised Exception"
        )
    except AssertionError:
        pass
    await configured_client.auth_to_lab()
    # Do things with the lab.
    async with configured_client.open_lab_session() as lab_session:
        code = "print(2+2)"
        four = (await lab_session.run_python(code)).strip()
        assert four == "4"
        hello = await lab_session.run_notebook(Path("hello.ipynb"))
        assert hello == ["Hello, world!\n"]
        ner = await lab_session.run_notebook_via_rsp_extension(
            path=Path("hello.ipynb")
        )
        assert ner.error is None

    # Stop the lab
    await configured_client.stop_lab()
    # Is the lab running?  Should not be.
    assert await configured_client.is_lab_stopped()