import pytest

from jupyterlabcontroller.models.context import Context

from ..settings import TestObjectFactory


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
) -> None:
    user = await user_context.get_user()
    lm = user_context.lab_manager
    nss = lm.build_nss(user=user)
    assert nss["/etc/passwd"].endswith(
        "lsst_lcl:x:1000:1000::/home/lsst_lcl:/bin/bash\n"
        "rachel:x:1101:1101:Rachel (?):/home/rachel:/bin/bash\n"
    )
    assert nss["/etc/group"].endswith(
        "input:x:999:\n"
        "rachel:x:1101:\n"
        "lunatics:x:2028:rachel\n"
        "mechanics:x:2001:rachel\n"
        "storytellers:x:2021:rachel\n"
    )


@pytest.mark.asyncio
async def test_configmap(
    obj_factory: TestObjectFactory,
    user_context: Context,
) -> None:
    lm = user_context.lab_manager
    cm = lm.build_file_configmap()
    assert cm["/opt/lsst/software/jupyterlab/panda"].endswith(
        "cacher_dir = /data/idds\n"
    )


@pytest.mark.asyncio
async def test_env(
    obj_factory: TestObjectFactory,
    user_context: Context,
) -> None:
    lab = obj_factory.labspecs[0]
    user = await user_context.get_user()
    token = user_context.token
    lm = user_context.lab_manager
    env = lm.build_env(user=user, lab=lab, token=token)
    # Take one variable from each merge category
    assert env["FIREFLY_ROUTE"] == "/portal/app"
    assert env["IMAGE_DIGEST"] == "1234"
    assert env["CPU_LIMIT"] == "1.0"
    assert env["EXTERNAL_UID"] == "1101"
    assert env["ACCESS_TOKEN"] == "token-of-affection"
    assert env["JUPYTERHUB_SERVICE_PREFIX"] == "/nb/user/rachel"


@pytest.mark.asyncio
async def test_vols(
    obj_factory: TestObjectFactory,
    user_context: Context,
) -> None:
    user = await user_context.get_user()
    username = user.username
    lm = user_context.lab_manager
    vols = lm.build_volumes(username=username)
    vnames = [x.volume.name for x in vols]
    assert vnames == [
        "home",
        "project",
        "scratch",
        "nss-rachel-passwd",
        "nss-rachel-group",
        "nss-rachel-lsst-dask-yml",
        "nss-rachel-panda",
        "nb-rachel-secrets",
        "nb-rachel-env",
        "tmp",
        "nb-rachel-runtime",
    ]


@pytest.mark.asyncio
async def test_pod_spec(
    obj_factory: TestObjectFactory,
    user_context: Context,
) -> None:
    lab = obj_factory.labspecs[0]
    user = await user_context.get_user()
    lm = user_context.lab_manager
    ps = lm.build_pod_spec(user=user, lab=lab)
    ctr = ps.containers[0]
    assert ps.volumes[-3].config_map.name == "nb-rachel-env"
    assert ps.security_context.fs_group == 1101
    assert ps.security_context.supplemental_groups[1] == 2028
    assert ctr.env_from.config_map_ref.name == "nb-rachel-env"
    assert ctr.security_context.privileged is None
    assert ctr.volume_mounts[1].mount_path == "/project"
