import pytest
from structlog.stdlib import BoundLogger

from jupyterlabcontroller.config import Configuration
from jupyterlabcontroller.models.context import Context
from jupyterlabcontroller.models.domain.usermap import UserMap
from jupyterlabcontroller.services.lab import DeleteLabManager, LabManager
from jupyterlabcontroller.services.prepuller import PrepullerManager
from jupyterlabcontroller.storage.k8s import K8sStorageClient

from ..settings import TestObjectFactory


@pytest.mark.asyncio
async def test_lab_manager(
    obj_factory: TestObjectFactory,
    prepuller_manager: PrepullerManager,
    user_context: Context,
    logger: BoundLogger,
    config: Configuration,
    k8s_storage_client: K8sStorageClient,
    user_map: UserMap,
) -> None:
    lab = obj_factory.labspecs[0]
    assert user_context.user is not None
    user = user_context.user
    username = user.username
    namespace = user_context.namespace
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
        prepuller_manager=prepuller_manager,
        logger=logger,
        lab_config=lab_config,
        k8s_client=k8s_storage_client,
        user=user,
        token=token,
    )
    present = await lm.check_for_user()
    assert present is True  # It should already be in the user map
    dlm = DeleteLabManager(
        user_map=user_map, k8s_client=k8s_storage_client, logger=logger
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
    prepuller_manager: PrepullerManager,
    user_context: Context,
    logger: BoundLogger,
    config: Configuration,
    k8s_storage_client: K8sStorageClient,
    user_map: UserMap,
) -> None:
    lab = obj_factory.labspecs[0]
    assert user_context.user is not None
    user = user_context.user
    username = user.username
    namespace = user_context.namespace
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
        prepuller_manager=prepuller_manager,
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
    prepuller_manager: PrepullerManager,
    user_context: Context,
    logger: BoundLogger,
    config: Configuration,
    k8s_storage_client: K8sStorageClient,
    user_map: UserMap,
) -> None:
    lab = obj_factory.labspecs[0]
    assert user_context.user is not None
    user = user_context.user
    username = user.username
    namespace = user_context.namespace
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
        prepuller_manager=prepuller_manager,
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
    prepuller_manager: PrepullerManager,
    user_context: Context,
    logger: BoundLogger,
    config: Configuration,
    k8s_storage_client: K8sStorageClient,
    user_map: UserMap,
) -> None:
    lab = obj_factory.labspecs[0]
    assert user_context.user is not None
    user = user_context.user
    username = user.username
    namespace = user_context.namespace
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
        prepuller_manager=prepuller_manager,
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
