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
