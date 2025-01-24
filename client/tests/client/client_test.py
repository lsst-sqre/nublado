"""Tests for the NubladoClient object."""

import asyncio
from contextlib import aclosing
from pathlib import Path

import pytest

from rubin.nublado.client import NubladoClient
from rubin.nublado.client.exceptions import CodeExecutionError
from rubin.nublado.client.models import (
    NubladoImageByClass,
    NubladoImageClass,
    NubladoImageSize,
)
from rubin.nublado.client.testing import MockJupyter


@pytest.mark.asyncio
async def test_hub_flow(
    configured_client: NubladoClient, jupyter: MockJupyter
) -> None:
    """Check that the Hub operations work as expected."""
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
    async with aclosing(progress):
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

        # Try something that will raise an exception and test that
        # the CodeErrorException contains all the things we expect.
        with pytest.raises(CodeExecutionError) as excinfo:
            await lab_session.run_notebook(Path("faux-input.ipynb"))
        exc = excinfo.value
        anno = exc.annotations
        assert anno["cell"] == "3462f36e-b3db-42b5-8669-81d9acbe6424"
        assert anno["cell_number"] == "#1"
        assert anno["cell_source"] == (
            "What do you get when you multipy six by nine?"
        )
        assert anno["cell_line_number"] == "#1"
        assert anno["cell_line_source"] == (
            "What do you get when you multipy six by nine?"
        )
        assert anno["notebook"] == "faux-input.ipynb"
        assert anno["path"] == "faux-input.ipynb"
        assert exc.error is not None
        assert exc.error.startswith("Traceback (most recent call last):")
        assert exc.error.endswith("SyntaxError: invalid syntax\n")
        assert exc.code == "What do you get when you multipy six by nine?"

    # Stop the lab
    await configured_client.stop_lab()
    # Is the lab running?  Should not be.
    assert await configured_client.is_lab_stopped()
