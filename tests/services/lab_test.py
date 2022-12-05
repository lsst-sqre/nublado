import pytest
from structlog.stdlib import BoundLogger

from jupyterlabcontroller.config import Configuration
from jupyterlabcontroller.models.context import Context
from jupyterlabcontroller.models.domain.usermap import UserMap
from jupyterlabcontroller.services.lab import DeleteLabManager, LabManager
from jupyterlabcontroller.storage.k8s import K8sStorageClient

from ..settings import TestObjectFactory


@pytest.mark.asyncio
async def test_lab_manager(
    obj_factory: TestObjectFactory,
    context: Context,
    user_token: str,
    logger: BoundLogger,
    config: Configuration,
    user_map: UserMap,
) -> None:
    lab = obj_factory.labspecs[0]
    user = await context.get_user()
    username = user.username
    namespace = await context.get_namespace()
    token = context.token
    manager_namespace = config.runtime.namespace_prefix
    instance_url = config.runtime.instance_url
    lab_config = config.lab
    lm = LabManager(
        username=username,
        namespace=namespace,
        manager_namespace=manager_namespace,
        instance_url=instance_url,
        user_map=user_map,
        lab=lab,
        logger=logger,
        lab_config=lab_config,
        k8s_client=context.k8s_client,
        user=user,
        token=token,
    )
    present = await lm.check_for_user()
    assert present is True  # It should already be in the user map
    dlm = DeleteLabManager(
        user_map=user_map, k8s_client=context.k8s_client, logger=logger
    )
    await dlm.delete_lab_environment(username=username)
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


@pytest.mark.asyncio
async def test_nss(
    obj_factory: TestObjectFactory,
    user_context: Context,
    logger: BoundLogger,
    config: Configuration,
    k8s_storage_client: K8sStorageClient,
    user_map: UserMap,
) -> None:
    lab = obj_factory.labspecs[0]
    user = await user_context.get_user()
    username = user.username
    namespace = await user_context.get_namespace()
    token = user_context.token
    manager_namespace = config.runtime.namespace_prefix
    instance_url = config.runtime.instance_url
    lab_config = config.lab
    lm = LabManager(
        username=username,
        namespace=namespace,
        manager_namespace=manager_namespace,
        instance_url=instance_url,
        user_map=user_map,
        lab=lab,
        logger=logger,
        lab_config=lab_config,
        k8s_client=k8s_storage_client,
        user=user,
        token=token,
    )
    nss = await lm.build_nss()
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
    logger: BoundLogger,
    config: Configuration,
    k8s_storage_client: K8sStorageClient,
    user_map: UserMap,
) -> None:
    lab = obj_factory.labspecs[0]
    user = await user_context.get_user()
    username = user.username
    namespace = await user_context.get_namespace()
    token = user_context.token
    manager_namespace = config.runtime.namespace_prefix
    instance_url = config.runtime.instance_url
    lab_config = config.lab
    lm = LabManager(
        username=username,
        namespace=namespace,
        manager_namespace=manager_namespace,
        instance_url=instance_url,
        user_map=user_map,
        lab=lab,
        logger=logger,
        lab_config=lab_config,
        k8s_client=k8s_storage_client,
        user=user,
        token=token,
    )
    cm = await lm.build_file_configmap()
    assert cm["/opt/lsst/software/jupyterlab/panda"].endswith(
        "cacher_dir = /data/idds\n"
    )


@pytest.mark.asyncio
async def test_env(
    obj_factory: TestObjectFactory,
    user_context: Context,
    logger: BoundLogger,
    config: Configuration,
    k8s_storage_client: K8sStorageClient,
    user_map: UserMap,
) -> None:
    lab = obj_factory.labspecs[0]
    user = await user_context.get_user()
    username = user.username
    namespace = await user_context.get_namespace()
    token = user_context.token
    manager_namespace = config.runtime.namespace_prefix
    instance_url = config.runtime.instance_url
    lab_config = config.lab
    lm = LabManager(
        username=username,
        namespace=namespace,
        manager_namespace=manager_namespace,
        instance_url=instance_url,
        user_map=user_map,
        lab=lab,
        logger=logger,
        lab_config=lab_config,
        k8s_client=k8s_storage_client,
        user=user,
        token=token,
    )
    env = await lm.build_env()
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
    logger: BoundLogger,
    config: Configuration,
    k8s_storage_client: K8sStorageClient,
    user_map: UserMap,
) -> None:
    lab = obj_factory.labspecs[0]
    user = await user_context.get_user()
    username = user.username
    namespace = await user_context.get_namespace()
    token = user_context.token
    manager_namespace = config.runtime.namespace_prefix
    instance_url = config.runtime.instance_url
    lab_config = config.lab
    lm = LabManager(
        username=username,
        namespace=namespace,
        manager_namespace=manager_namespace,
        instance_url=instance_url,
        user_map=user_map,
        lab=lab,
        logger=logger,
        lab_config=lab_config,
        k8s_client=k8s_storage_client,
        user=user,
        token=token,
    )
    vols = await lm.build_volumes()
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
    logger: BoundLogger,
    config: Configuration,
    k8s_storage_client: K8sStorageClient,
    user_map: UserMap,
) -> None:
    lab = obj_factory.labspecs[0]
    user = await user_context.get_user()
    username = user.username
    namespace = await user_context.get_namespace()
    token = user_context.token
    manager_namespace = config.runtime.namespace_prefix
    instance_url = config.runtime.instance_url
    lab_config = config.lab
    lm = LabManager(
        username=username,
        namespace=namespace,
        manager_namespace=manager_namespace,
        instance_url=instance_url,
        user_map=user_map,
        lab=lab,
        logger=logger,
        lab_config=lab_config,
        k8s_client=k8s_storage_client,
        user=user,
        token=token,
    )
    ps = await lm.build_pod_spec(user=user)
    ctr = ps.containers[0]
    assert ps.volumes[-3].config_map.name == "nb-rachel-env"
    assert ps.security_context.fs_group == 1101
    assert ps.security_context.supplemental_groups[1] == 2028
    assert ctr.env_from.config_map_ref.name == "nb-rachel-env"
    assert ctr.security_context.privileged is None
    assert ctr.volume_mounts[1].mount_path == "/project"
