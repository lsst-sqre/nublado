import pytest

from jupyterlabcontroller.factory import Context
from jupyterlabcontroller.models.v1.prepuller import Image


@pytest.mark.asyncio
async def test_get_menu_images(user_context: Context) -> None:
    r = user_context.prepuller_arbitrator.get_menu_images()
    assert "Recommended" in r.menu
    assert type(r.menu["Recommended"]) is Image
    assert r.menu["Recommended"].digest == "sha256:5678"


@pytest.mark.asyncio
async def test_get_prepulls(user_context: Context) -> None:
    px = user_context.prepuller_executor
    await px.k8s_client.refresh_state_from_k8s()
    await px.docker_client.refresh_state_from_docker_repo()
    r = user_context.prepuller_arbitrator.get_prepulls()
    assert r.config.docker is not None
    assert r.config.docker.repository == "library/sketchbook"
    assert r.images.prepulled[0].digest == "sha256:5678"
    assert r.nodes[0].name == "node1"
