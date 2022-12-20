import pytest

from rsp_restspawner.spawner import RSPRestSpawner


@pytest.mark.asyncio
async def test_spawner_creation() -> None:
    _ = RSPRestSpawner()
    assert True
