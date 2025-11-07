"""Tests for the Nublado client."""

from __future__ import annotations

from contextlib import aclosing
from dataclasses import dataclass
from uuid import UUID

import pytest

from rubin.nublado.client import (
    MockJupyter,
    NubladoClient,
    NubladoImage,
    NubladoImageByClass,
    NubladoImageByReference,
    NubladoImageByTag,
    NubladoImageClass,
    NubladoImageSize,
)


@pytest.mark.asyncio
async def test_hub_flow(
    client: NubladoClient, username: str, mock_jupyter: MockJupyter
) -> None:
    """Check that the Hub operations work as expected."""
    # Must authenticate first.
    with pytest.raises(AssertionError):
        assert await client.is_lab_stopped()

    await client.auth_to_hub()
    assert await client.is_lab_stopped()

    # Simulate spawn.
    await client.spawn_lab(
        NubladoImageByClass(
            image_class=NubladoImageClass.RECOMMENDED,
            size=NubladoImageSize.Medium,
        )
    )
    assert mock_jupyter.get_last_spawn_form(username) == {
        "image_class": "recommended",
        "size": "Medium",
    }

    # Watch the progress meter.
    progress = -1
    async with aclosing(client.watch_spawn_progress()) as spawn_progress:
        async for message in spawn_progress:
            if message.ready:
                break
            assert message.progress > progress
            progress = message.progress

    # Lab should now be running. Execute some code.
    assert not await client.is_lab_stopped()
    assert mock_jupyter.get_session(username) is None
    async with client.lab_session() as session:
        result = await session.run_python("print(2+2)")
        assert result.strip() == "4"

        # Check the parameters of the session.
        session_data = mock_jupyter.get_session(username)
        assert session_data
        assert session_data.kernel_name == "LSST"
        assert session_data.name == "(no notebook)"
        assert UUID(session_data.path)
        assert session_data.type == "console"

    # Create a session with a notebook name.
    async with client.lab_session(
        "notebook.ipynb", kernel_name="custom"
    ) as session:
        result = await session.run_python("print(3+2)")
        assert result.strip() == "5"

        # Check the parameters of the session.
        session_data = mock_jupyter.get_session(username)
        assert session_data
        assert session_data.kernel_name == "custom"
        assert session_data.name == "notebook.ipynb"
        assert session_data.path == "notebook.ipynb"
        assert session_data.type == "notebook"

    # Stop the lab
    await client.stop_lab()
    assert await client.is_lab_stopped()


@dataclass
class FormTestCase:
    image: NubladoImage
    form: dict[str, str]


@pytest.mark.asyncio
async def test_lab_form(
    client: NubladoClient, username: str, mock_jupyter: MockJupyter
) -> None:
    await client.auth_to_hub()

    # List of NubladoImage objects to pass in to spawn and the expected
    # submitted lab form.
    test_cases = [
        FormTestCase(
            image=NubladoImageByReference(
                reference="example/lab:some-tag", debug=True
            ),
            form={
                "image_list": "example/lab:some-tag",
                "size": "Large",
                "enable_debug": "true",
            },
        ),
        FormTestCase(
            image=NubladoImageByTag(tag="some-tag"),
            form={"image_tag": "some-tag", "size": "Large"},
        ),
        FormTestCase(
            image=NubladoImageByClass(),
            form={"image_class": "recommended", "size": "Large"},
        ),
        FormTestCase(
            image=NubladoImageByClass(
                image_class=NubladoImageClass.LATEST_RELEASE,
                size=NubladoImageSize.Small,
                debug=True,
            ),
            form={
                "image_class": "latest-release",
                "size": "Small",
                "enable_debug": "true",
            },
        ),
    ]

    # For each of the test cases, spawn a lab and check the lab form.
    for test_case in test_cases:
        await client.spawn_lab(test_case.image)
        assert mock_jupyter.get_last_spawn_form(username) == test_case.form
        await client.wait_for_spawn()
        await client.stop_lab()
