import pytest

from jupyterlabcontroller.storage.prepuller import PrepullerClient


@pytest.mark.asyncio
async def test_get_current_image_and_node_state(
    prepuller_dep: PrepullerClient,
) -> None:
    r = await prepuller_dep.get_current_image_and_node_state()
    print(r)
