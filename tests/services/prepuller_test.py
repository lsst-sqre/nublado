import asyncio

import pytest

from jupyterlabcontroller.models.v1.prepuller import Image
from jupyterlabcontroller.services.prepull_executor import PrepullExecutor


@pytest.mark.asyncio
async def test_get_menu_images(prepull_executor: PrepullExecutor) -> None:
    pm = prepull_executor.manager
    r = await pm.get_menu_images()
    assert "recommended" in r
    assert type(r["recommended"]) is Image
    assert r["recommended"].digest == "sha256:5678"


@pytest.mark.asyncio
async def test_get_prepulls(prepull_executor: PrepullExecutor) -> None:
    pm = prepull_executor.manager
    r = await pm.get_prepulls()
    assert r.config.docker is not None
    assert r.config.docker.repository == "library/sketchbook"
    assert (
        r.images.prepulled[0].path
        == "lighthouse.ceres/library/sketchbook:recommended"
    )
    assert r.nodes[0].name == "node1"


@pytest.mark.asyncio
async def test_run_prepuller(prepull_executor: PrepullExecutor) -> None:
    await prepull_executor.run()
    await asyncio.sleep(0.2)
    await prepull_executor.stop()
    await asyncio.sleep(0.2)
