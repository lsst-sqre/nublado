import pytest

from jupyterlabcontroller.models.context import Context
from jupyterlabcontroller.services.lab import LabManager

from ..settings import TestObjectFactory


@pytest.mark.asyncio
async def test_lab_manager(
    obj_factory: TestObjectFactory,
    user_context: Context,
) -> None:
    lab = obj_factory.labspecs[0]
    lm = LabManager(
        lab=lab,
        context=user_context,
    )
    present = await lm.check_for_user()
    assert present is True  # It should already be in the user map
    await lm.delete_lab_environment(username=lm.user)
    present = await lm.check_for_user()
    assert present is False  # And now it should not be
    await lm.create_lab()
    present = await lm.check_for_user()
    assert present is True  # And should now have returned


@pytest.mark.asyncio
async def test_get_active_users(
    obj_factory: TestObjectFactory,
    user_context: Context,
) -> None:
    users = user_context.user_map.running
    assert len(users) == 1
    assert users[0] == "wrench"
