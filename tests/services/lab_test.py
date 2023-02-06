import json
from pathlib import Path

import pytest

from jupyterlabcontroller.factory import Context

from ..settings import TestObjectFactory
from ..support.check_file import check_file


@pytest.mark.asyncio
async def test_lab_manager(
    user_context: Context,
    obj_factory: TestObjectFactory,
) -> None:
    user = await user_context.get_user()
    username = user.username
    token = user_context.token
    lab = obj_factory.labspecs[0]
    lm = user_context.lab_manager
    present = lm.check_for_user(username)
    assert present is False  # User map should be empty
    await lm.create_lab(token=token, lab=lab)
    present = lm.check_for_user(username)
    assert present is True  # And should now have an entry
    # We couldn't really do this next thing through the handler with a
    # user token.
    await lm.delete_lab(username=username)
    await lm.await_ns_deletion(
        namespace=lm.namespace_from_user(user), username=username
    )
    present = lm.check_for_user(username)  # Deleted again
    assert present is False


@pytest.mark.asyncio
async def test_get_active_users(
    user_context: Context,
    obj_factory: TestObjectFactory,
) -> None:
    user = await user_context.get_user()
    username = user.username
    token = user_context.token
    lab = obj_factory.labspecs[0]
    lm = user_context.lab_manager
    users = await user_context.user_map.running()
    assert len(users) == 0
    await lm.create_lab(token=token, lab=lab)
    await lm.await_pod_spawn(
        namespace=lm.namespace_from_user(user), username=username
    )
    users = await user_context.user_map.running()
    assert len(users) == 1
    assert users[0] == "rachel"
    await lm.delete_lab(username=username)
    users = await user_context.user_map.running()
    assert len(users) == 0


@pytest.mark.asyncio
async def test_nss(
    obj_factory: TestObjectFactory,
    user_context: Context,
    std_result_dir: Path,
) -> None:
    user = await user_context.get_user()
    lm = user_context.lab_manager
    nss = lm.build_nss(user=user)
    for k in nss:
        dk = k.replace("/", "-")
        check_file(nss[k], std_result_dir / f"nss{dk}.txt")


@pytest.mark.asyncio
async def test_configmap(
    obj_factory: TestObjectFactory,
    user_context: Context,
    std_result_dir: Path,
) -> None:
    lm = user_context.lab_manager
    cm = lm.build_file_configmap()
    for k in cm:
        dk = k.replace("/", "-")
        check_file(cm[k], std_result_dir / f"cm{dk}.txt")


@pytest.mark.asyncio
async def test_env(
    obj_factory: TestObjectFactory,
    user_context: Context,
    std_result_dir: Path,
) -> None:
    lab = obj_factory.labspecs[0]
    user = await user_context.get_user()
    token = user_context.token
    lm = user_context.lab_manager
    env = lm.build_env(user=user, lab=lab, token=token)
    env_str = json.dumps(env, sort_keys=True, indent=4)
    check_file(env_str, std_result_dir / "env.json")


@pytest.mark.asyncio
async def test_vols(
    obj_factory: TestObjectFactory,
    user_context: Context,
    std_result_dir: Path,
) -> None:
    user = await user_context.get_user()
    username = user.username
    lm = user_context.lab_manager
    vols = lm.build_volumes(username=username)
    vol_str = "\n".join([f"{x}" for x in vols])
    check_file(vol_str, std_result_dir / "volumes.txt")


@pytest.mark.asyncio
async def test_pod_spec(
    obj_factory: TestObjectFactory,
    user_context: Context,
    std_result_dir: Path,
) -> None:
    lab = obj_factory.labspecs[0]
    user = await user_context.get_user()
    lm = user_context.lab_manager
    ps = lm.build_pod_spec(user=user, lab=lab)
    ps_str = f"{ps}"
    check_file(ps_str, std_result_dir / "podspec.txt")
