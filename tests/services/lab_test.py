import json
from pathlib import Path

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
    namespace = lab_manager.namespace_from_user(user)
    await lab_manager.await_ns_deletion(namespace, user.username)
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
    assert await factory.user_map.running() == []


@pytest.mark.asyncio
async def test_nss(
    factory: Factory, obj_factory: TestObjectFactory, std_result_dir: Path
) -> None:
    _, user = obj_factory.get_user()
    lab_manager = factory.create_lab_manager()
    nss = lab_manager.build_nss(user)
    for k in nss:
        dk = k.replace("/", "-")
        assert nss[k] == (std_result_dir / f"nss{dk}.txt").read_text()


@pytest.mark.asyncio
async def test_configmap(factory: Factory, std_result_dir: Path) -> None:
    lab_manager = factory.create_lab_manager()
    cm = lab_manager.build_file_configmap()
    for k in cm:
        dk = k.replace("/", "-")
        assert cm[k] == (std_result_dir / f"cm{dk}.txt").read_text()


@pytest.mark.asyncio
async def test_env(
    factory: Factory,
    obj_factory: TestObjectFactory,
    std_result_dir: Path,
) -> None:
    token, user = obj_factory.get_user()
    lab = obj_factory.labspecs[0]
    lab_manager = factory.create_lab_manager()

    env = lab_manager.build_env(user, lab, token)
    with (std_result_dir / "env.json").open("r") as f:
        expected = json.load(f)
    assert env == expected


@pytest.mark.asyncio
async def test_vols(
    factory: Factory,
    obj_factory: TestObjectFactory,
    std_result_dir: Path,
) -> None:
    _, user = obj_factory.get_user()
    lab_manager = factory.create_lab_manager()

    vols = lab_manager.build_volumes(user.username)
    vol_str = "\n".join([f"{x}" for x in vols])
    assert vol_str == (std_result_dir / "volumes.txt").read_text()


@pytest.mark.asyncio
async def test_pod_spec(
    factory: Factory, obj_factory: TestObjectFactory, std_result_dir: Path
) -> None:
    _, user = obj_factory.get_user()
    lab = obj_factory.labspecs[0]
    lab_manager = factory.create_lab_manager()

    ps = lab_manager.build_pod_spec(user, lab)
    assert str(ps) == (std_result_dir / "podspec.txt").read_text()
