import asyncio

import pytest

from jupyterlabcontroller.models.context import Context
from jupyterlabcontroller.models.v1.prepuller import Image
from jupyterlabcontroller.services.prepull_executor import PrepullExecutor
from jupyterlabcontroller.services.prepuller import PrepullerManager


@pytest.mark.asyncio
async def test_get_menu_images(user_context: Context) -> None:
    pm: PrepullerManager = PrepullerManager(context=user_context)
    r = await pm.get_menu_images()
    assert "recommended" in r
    assert type(r["recommended"]) is Image
    assert r["recommended"].digest == "sha256:5678"


@pytest.mark.asyncio
async def test_get_prepulls(user_context: Context) -> None:
    pm: PrepullerManager = PrepullerManager(context=user_context)
    r = await pm.get_prepulls()
    assert r.config.docker is not None
    assert r.config.docker.repository == "library/sketchbook"
    assert (
        r.images.prepulled[0].path
        == "lighthouse.ceres/library/sketchbook:recommended"
    )
    assert r.nodes[0].name == "node1"


@pytest.mark.asyncio
async def test_run_prepuller(user_context: Context) -> None:
    prepull_executor: PrepullExecutor = PrepullExecutor(context=user_context)
    await prepull_executor.run()
    await asyncio.sleep(0.2)
    await prepull_executor.stop()
    await asyncio.sleep(0.2)