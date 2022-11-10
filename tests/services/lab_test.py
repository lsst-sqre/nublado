import pytest

from jupyterlabcontroller.models.v1.domain.context import (
    ContextContainer,
    RequestContext,
)
from jupyterlabcontroller.services.lab import LabManager

from ..settings import TestObjectFactory


@pytest.mark.asyncio
async def test_lab_manager(
    obj_factory: TestObjectFactory,
    request_context: RequestContext,
    context_container: ContextContainer,
) -> None:
    lab = obj_factory.labspecs[0]
    lm = LabManager(
        lab=lab, nublado=context_container, context=request_context
    )
    present = await lm.check_for_user()
    assert present is True  # It should already be in the user map
    await lm.delete_lab_environment(username=lm.context.user.username)
    present = await lm.check_for_user()
    assert present is False  # And now it should not be
    await lm.create_lab()
    present = await lm.check_for_user()
    assert present is True  # And should now have returned
