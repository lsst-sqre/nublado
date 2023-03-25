"""Tests for the lab service."""

import asyncio

import pytest

from jupyterlabcontroller.factory import Factory

from ..settings import TestObjectFactory


@pytest.mark.asyncio
async def test_lab_manager(
    factory: Factory, obj_factory: TestObjectFactory
) -> None:
    token, user = obj_factory.get_user()
    lab = obj_factory.labspecs[0]
    lab_manager = factory.create_lab_manager()

    assert not lab_manager.check_for_user(user.username)
    await lab_manager.create_lab(user, token, lab)
    assert lab_manager.check_for_user(user.username)

    await lab_manager.delete_lab(user.username)
    assert not lab_manager.check_for_user(user.username)


@pytest.mark.asyncio
async def test_get_active_users(
    factory: Factory,
    obj_factory: TestObjectFactory,
) -> None:
    token, user = obj_factory.get_user()
    lab = obj_factory.labspecs[0]
    lab_manager = factory.create_lab_manager()

    assert await factory.user_map.running() == []

    await lab_manager.create_lab(user, token, lab)
    namespace = lab_manager.namespace_from_user(user)
    await lab_manager.await_pod_spawn(namespace, user.username)

    assert await factory.user_map.running() == [user.username]

    await lab_manager.delete_lab(user.username)

    # We have to let the background task run and complete the namespace
    # deletion.
    await asyncio.sleep(0.2)
    assert await factory.user_map.running() == []
