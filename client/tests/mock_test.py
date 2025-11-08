"""Test features of the Jupyter mock for the Nublado client."""

from __future__ import annotations

import pytest

from rubin.nublado.client import (
    MockJupyter,
    NubladoClient,
    NubladoExecutionError,
    NubladoImageByClass,
)


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
