import pytest

from jupyterlabcontroller.models.context import Context
from jupyterlabcontroller.models.v1.prepuller import Image


@pytest.mark.asyncio
async def test_get_menu_images(user_context: Context) -> None:
    r = user_context.prepuller_arbitrator.get_menu_images()
    assert "recommended" in r.menu
    assert type(r.menu["recommended"]) is Image
    assert r.menu["recommended"].digest == "sha256:5678"


@pytest.mark.asyncio
async def test_get_prepulls(user_context: Context) -> None:
    r = user_context.prepuller_arbitrator.get_prepulls()
    assert r.config.docker is not None
    assert r.config.docker.repository == "library/sketchbook"
    assert (
        r.images.prepulled[0].path
        == "lighthouse.ceres/library/sketchbook:recommended@sha256:5678"
    )
    assert r.nodes[0].name == "node1"
