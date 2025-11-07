"""Test features of the Jupyter mock for the Nublado client."""

import asyncio
import json
from contextlib import aclosing
from pathlib import Path

import pytest

from rubin.nublado.client import (
    MockJupyter,
    NotebookExecutionResult,
    NubladoClient,
    NubladoImageByClass,
    NubladoImageClass,
    NubladoImageSize,
)

INPUT_NB = Path(__file__).parent.parent / "support" / "faux-input-nb"
OUTPUT_NB = Path(__file__).parent.parent / "support" / "faux-output-nb"


@pytest.mark.asyncio
async def test_register_python(
    client: NubladoClient, mock_jupyter: MockJupyter
) -> None:
    """Register 'python' code with the mock and check its output."""
    code = "What do you get when you multiply six by nine?"
    # Register our code with the mock.
    mock_jupyter.register_python_result(code, "42")

    # Do the whole lab flow
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
    await client.auth_to_lab()

    # Now test our mock
    async with client.lab_session() as lab_session:
        forty_two = (await lab_session.run_python(code)).strip()
        assert forty_two == "42"

    # Stop the lab
    await client.stop_lab()
    # Is the lab running?  Should not be.
    assert await client.is_lab_stopped()


@pytest.mark.asyncio
async def test_register_extension(
    client: NubladoClient, mock_jupyter: MockJupyter
) -> None:
    """Register 'python' code with the mock and check its output."""
    # Register our code with the mock.
    mock_jupyter.register_notebook_result(
        INPUT_NB.read_text(),
        NotebookExecutionResult(notebook=OUTPUT_NB.read_text(), resources={}),
    )

    # Do the whole lab flow
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
    await client.auth_to_lab()

    # Now test our mock
    ner = await client.run_notebook(INPUT_NB.read_text())
    ner_out = json.dumps(json.loads(ner.notebook)["cells"][0]["outputs"])
    supplied_out = json.dumps(
        json.loads(OUTPUT_NB.read_text())["cells"][0]["outputs"]
    )
    assert ner_out == supplied_out
    assert ner.resources == {}
    assert ner.error is None

    # Stop the lab
    await client.stop_lab()
    # Is the lab running?  Should not be.
    assert await client.is_lab_stopped()
