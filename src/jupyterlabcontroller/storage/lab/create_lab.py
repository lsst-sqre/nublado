import asyncio
from collections import deque
from copy import copy
from typing import Dict

from aiojobs import Scheduler
from fastapi import Depends
from kubernetes_asyncio.client import ApiClient, CoreV1Api
from kubernetes_asyncio.client.models import V1Namespace
from kubernetes_asyncio.client.rest import ApiException
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ....config import config
from ....dependencies.k8s import k8s_api_dependency, k8s_corev1api_dependency
from ....dependencies.labs import lab_dependency
from ....dependencies.namespace import namespace_dependency
from ....dependencies.token import token_dependency, user_dependency
from ....models.v1.external.userdata import (
    LabSpecification,
    UserData,
    UserInfo,
)
from ....services.quota import quota_from_size
from .delete_lab import delete_namespace
from .std_metadata import get_std_metadata


async def create_lab_environment(
    lab: LabSpecification,
    user: UserInfo = Depends(user_dependency),
    token: str = Depends(token_dependency),
    logger: BoundLogger = Depends(logger_dependency),
    labs: Dict[str, UserData] = Depends(lab_dependency),
) -> None:
    username = user.username
    labs[username] = UserData(
        username=username,
        status="starting",
        pod="missing",
        options=copy(lab.options),
        env=copy(lab.env),
        uid=user.uid,
        gid=user.gid,
        groups=copy(user.groups),
        quotas=quota_from_size(lab.options.size),
    )
    try:
        await create_user_namespace()
        await create_user_lab_objects(lab)
        await create_user_lab_pod(lab)
    except Exception as e:
        labs[username].status = "failed"
        logger.error(f"User lab creation for {username} failed: {e}")
        raise
    # user creation was successful; drop events.
    labs[username].pod = "present"
    labs[username].events = deque()
    return


async def create_user_namespace(
    user: UserInfo = Depends(user_dependency),
    api: ApiClient = Depends(k8s_corev1api_dependency),
    ns_name: str = Depends(namespace_dependency),
    logger: BoundLogger = Depends(logger_dependency),
) -> str:
    try:
        await asyncio.wait_for(
            api.create_namespace(
                V1Namespace(metadata=get_std_metadata(name=ns_name))
            ),
            config.k8s.request_timeout,
        )
    except ApiException as e:
        if e.status == 409:
            logger.info(f"Namespace {ns_name} already exists")
            # ... but we know that we don't have a lab for the user, because
            # we got this far.  So there's a stranded namespace, and we should
            # delete it and recreate it.
            #
            # The spec actually calls for us to delete the lab and then the
            # namespace, but let's just remove the namespace, which should
            # also clean up all its contents.
            await delete_namespace()
            # And just try again, and return *that* one's return code.
            return await create_user_namespace()
        else:
            logger.exception(f"Failed to create namespace {ns_name}: {e}")
            raise
    return ns_name


async def create_user_lab_objects(
    lab: LabSpecification,
    user: UserInfo = Depends(user_dependency),
    token: str = Depends(token_dependency),
    namespace: str = Depends(namespace_dependency),
    api: ApiClient = Depends(k8s_corev1api_dependency),
) -> None:
    # Initially this will create all the resources in parallel.  If it turns
    # out we need to sequence that, we do this more manually with explicit
    # awaits.
    scheduler: Scheduler = Scheduler(close_timeout=config.k8s.request_timeout)
    scheduler.schedule(
        create_secrets(
            lab=lab,
        )
    )
    scheduler.schedule(
        create_nss(
            lab=lab,
        )
    )
    scheduler.schedule(
        create_env(
            lab=lab,
        )
    )
    scheduler.schedule(
        create_network_policy(
            lab=lab,
        )
    )
    scheduler.schedule(
        create_quota(
            lab=lab,
        )
    )
    await scheduler.close()
    return


async def create_secrets(
    lab: LabSpecification,
    user: UserInfo = Depends(user_dependency),
    namespace: str = Depends(namespace_dependency),
    api: ApiClient = Depends(k8s_corev1api_dependency),
    token: str = Depends(token_dependency),
) -> None:
    return


async def create_nss(
    lab: LabSpecification,
    user: UserInfo = Depends(user_dependency),
    namespace: str = Depends(namespace_dependency),
    api: CoreV1Api = Depends(k8s_corev1api_dependency),
    token: str = Depends(token_dependency),
) -> None:
    return


async def create_env(
    lab: LabSpecification,
    user: UserInfo = Depends(user_dependency),
    namespace: str = Depends(namespace_dependency),
    api: CoreV1Api = Depends(k8s_corev1api_dependency),
    token: str = Depends(token_dependency),
) -> None:
    return


async def create_network_policy(
    lab: LabSpecification,
    user: UserInfo = Depends(user_dependency),
    api: ApiClient = Depends(k8s_api_dependency),
    namespace: str = Depends(namespace_dependency),
    token: str = Depends(token_dependency),
) -> None:
    return


async def create_quota(
    lab: LabSpecification,
    user: UserInfo = Depends(user_dependency),
    api: ApiClient = Depends(k8s_api_dependency),
    namespace: str = Depends(namespace_dependency),
    token: str = Depends(token_dependency),
) -> None:
    return


async def create_user_lab_pod(
    lab: LabSpecification,
    user: UserInfo = Depends(user_dependency),
    api: ApiClient = Depends(k8s_api_dependency),
    namespace: str = Depends(namespace_dependency),
    token: str = Depends(token_dependency),
) -> None:
    return
