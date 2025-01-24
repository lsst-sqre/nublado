"""Test features of the Jupyter mock for the Nublado client."""

import asyncio
import json
from contextlib import aclosing
from pathlib import Path

import pytest

from rubin.nublado.client import NubladoClient
from rubin.nublado.client.models import (
    NotebookExecutionResult,
    NubladoImageByClass,
    NubladoImageClass,
    NubladoImageSize,
)
from rubin.nublado.client.testing import MockJupyter

INPUT_NB = Path(__file__).parent.parent / "support" / "faux-input-nb"
OUTPUT_NB = Path(__file__).parent.parent / "support" / "faux-output-nb"


@pytest.mark.asyncio
async def test_register_python(
    configured_client: NubladoClient, jupyter: MockJupyter
) -> None:
    """Register 'python' code with the mock and check its output."""
    code = "What do you get when you multiply six by nine?"
    # Register our code with the mock.
    jupyter.register_python_result(code, "42")

    # Do the whole lab flow
    await configured_client.auth_to_hub()
    assert await configured_client.is_lab_stopped()
    # Simulate spawn
    await configured_client.spawn_lab(
        NubladoImageByClass(
            image_class=NubladoImageClass.RECOMMENDED,
            size=NubladoImageSize.Medium,
            description="Recommended (Weekly 2077_44)",
        )
    )
    # Watch the progress meter
    progress = configured_client.watch_spawn_progress()
    progress_pct = -1
    async with aclosing(progress):
        async with asyncio.timeout(30):
            async for message in progress:
                if message.ready:
                    break
                assert message.progress > progress_pct
                progress_pct = message.progress
    await configured_client.auth_to_lab()

    # Now test our mock
    async with configured_client.open_lab_session() as lab_session:
        forty_two = (await lab_session.run_python(code)).strip()
        assert forty_two == "42"

    # Stop the lab
    await configured_client.stop_lab()
    # Is the lab running?  Should not be.
    assert await configured_client.is_lab_stopped()


@pytest.mark.asyncio
async def test_register_python_with_notebook(
    configured_client: NubladoClient, jupyter: MockJupyter
) -> None:
    """Register 'python' code with the mock and check its output."""
    obj = json.loads(INPUT_NB.read_text())
    sources = [
        "\n".join(x["source"]).strip().rstrip("\n")
        for x in obj["cells"]
        if x["cell_type"] == "code"
        and "".join(x["source"]).strip().rstrip("\n")
    ]
    sources[-1] = sources[-1].rstrip("\n")
    assert len(sources) == 1

    # Register our code with the mock.
    jupyter.register_python_result(sources[0], "42")

    # Do the whole lab flow
    await configured_client.auth_to_hub()
    assert await configured_client.is_lab_stopped()
    # Simulate spawn
    await configured_client.spawn_lab(
        NubladoImageByClass(
            image_class=NubladoImageClass.RECOMMENDED,
            size=NubladoImageSize.Medium,
            description="Recommended (Weekly 2077_44)",
        )
    )
    # Watch the progress meter
    progress = configured_client.watch_spawn_progress()
    progress_pct = -1
    async with aclosing(progress):
        async with asyncio.timeout(30):
            async for message in progress:
                if message.ready:
                    break
                assert message.progress > progress_pct
                progress_pct = message.progress
    await configured_client.auth_to_lab()

    # Now test our mock
    async with configured_client.open_lab_session() as lab_session:
        forty_two = (await lab_session.run_notebook(Path("faux-input.ipynb")))[
            0
        ].strip()
        assert forty_two == "42"

    # Stop the lab
    await configured_client.stop_lab()
    # Is the lab running?  Should not be.
    assert await configured_client.is_lab_stopped()


@pytest.mark.asyncio
async def test_register_extension(
    configured_client: NubladoClient, jupyter: MockJupyter
) -> None:
    """Register 'python' code with the mock and check its output."""
    # Register our code with the mock.
    jupyter.register_extension_result(
        INPUT_NB.read_text(),
        NotebookExecutionResult(notebook=OUTPUT_NB.read_text(), resources={}),
    )

    # Do the whole lab flow
    await configured_client.auth_to_hub()
    assert await configured_client.is_lab_stopped()
    # Simulate spawn
    await configured_client.spawn_lab(
        NubladoImageByClass(
            image_class=NubladoImageClass.RECOMMENDED,
            size=NubladoImageSize.Medium,
            description="Recommended (Weekly 2077_44)",
        )
    )
    # Watch the progress meter
    progress = configured_client.watch_spawn_progress()
    progress_pct = -1
    async with aclosing(progress):
        async with asyncio.timeout(30):
            async for message in progress:
                if message.ready:
                    break
                assert message.progress > progress_pct
                progress_pct = message.progress
    await configured_client.auth_to_lab()

    # Now test our mock
    async with configured_client.open_lab_session() as lab_session:
        ner = await lab_session.run_notebook_via_rsp_extension(
            path=Path("faux-input.ipynb")
        )
        ner_out = json.dumps(json.loads(ner.notebook)["cells"][0]["outputs"])
        supplied_out = json.dumps(
            json.loads(OUTPUT_NB.read_text())["cells"][0]["outputs"]
        )
        assert ner_out == supplied_out
        assert ner.resources == {}
        assert ner.error is None

    # Stop the lab
    await configured_client.stop_lab()
    # Is the lab running?  Should not be.
    assert await configured_client.is_lab_stopped()
