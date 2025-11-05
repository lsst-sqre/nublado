"""Tests for the NubladoClient object."""

import asyncio
from contextlib import aclosing
from pathlib import Path

import pytest

from rubin.nublado.client import (
    NubladoClient,
    NubladoImageByClass,
    NubladoImageClass,
    NubladoImageSize,
)


@pytest.mark.asyncio
async def test_hub_flow(client: NubladoClient) -> None:
    """Check that the Hub operations work as expected."""
    # Must authenticate first.
    with pytest.raises(AssertionError):
        assert await client.is_lab_stopped()

    await client.auth_to_hub()
    assert await client.is_lab_stopped()

    # Simulate spawn
    await client.spawn_lab(
        NubladoImageByClass(
            image_class=NubladoImageClass.RECOMMENDED,
            size=NubladoImageSize.Medium,
        )
    )
    # Watch the progress meter
    progress = client.watch_spawn_progress()
    progress_pct = -1
    async with aclosing(progress):
        async with asyncio.timeout(30):
            async for message in progress:
                if message.ready:
                    break
                assert message.progress > progress_pct
                progress_pct = message.progress

    # Is the lab running?  Should be.
    assert not await client.is_lab_stopped()

    # Do things with the lab.
    async with client.open_lab_session() as lab_session:
        code = "print(2+2)"
        four = (await lab_session.run_python(code)).strip()
        assert four == "4"

    # Run a complete notebook.
    notebook_path = Path(__file__).parent.parent / "support" / "hello.ipynb"
    ner = await client.run_notebook(notebook_path.read_text())
    assert ner.error is None

    # Stop the lab
    await client.stop_lab()
    # Is the lab running?  Should not be.
    assert await client.is_lab_stopped()
