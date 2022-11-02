import asyncio

import pytest
from aiojobs import Scheduler

from jupyterlabcontroller.models.v1.domain.context import (
    ContextContainer,
    RequestContext,
)
from jupyterlabcontroller.models.v1.external.prepuller import Image
from jupyterlabcontroller.services.prepuller import (
    PrepullerManager,
    PrepullExecutor,
)


@pytest.mark.asyncio
async def test_get_menu_images(
    request_context: RequestContext, context_container: ContextContainer
) -> None:
    pm: PrepullerManager = PrepullerManager(
        nublado=context_container, context=request_context
    )
    r = await pm.get_menu_images()
    assert "recommended" in r
    assert type(r["recommended"]) is Image
    assert r["recommended"].digest == "sha256:5678"


@pytest.mark.asyncio
async def test_get_prepulls(
    request_context: RequestContext, context_container: ContextContainer
) -> None:
    pm: PrepullerManager = PrepullerManager(
        nublado=context_container, context=request_context
    )
    r = await pm.get_prepulls()
    assert r.config.docker is not None
    assert r.config.docker.repository == "library/sketchbook"
    assert (
        r.images.prepulled[0].path
        == "lighthouse.ceres/library/sketchbook:recommended"
    )
    assert r.nodes[0].name == "node1"


@pytest.mark.asyncio
async def test_run_prepuller(
    request_context: RequestContext, context_container: ContextContainer
) -> None:
    prepull_executor: PrepullExecutor = PrepullExecutor(
        nublado=context_container, context=request_context
    )
    scheduler: Scheduler = Scheduler(
        close_timeout=context_container.config.kubernetes.request_timeout
    )
    await scheduler.spawn(prepull_executor.run())
    await asyncio.sleep(0.1)
    await prepull_executor.stop()
    await asyncio.sleep(0.1)
    await scheduler.close()
