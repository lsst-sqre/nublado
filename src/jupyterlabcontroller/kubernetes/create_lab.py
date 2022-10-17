import asyncio
from copy import copy

from fastapi import Depends
from kubernetes_asyncio.client import api_client
from kubernetes_asyncio.client.models import V1Namespace
from kubernetes_asyncio.client.rest import ApiException
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger

from ..config import config
from ..dependencies.k8s_corev1_api import corev1_api_dependency
from ..models.userdata import LabSpecification, UserData, UserInfo
from ..runtime.labs import labs
from ..runtime.namespace import get_user_namespace
from ..runtime.quota import quota_from_size
from .delete_lab import delete_namespace
from .std_metadata import get_std_metadata

__all__ = ["create_lab_environment"]


async def create_lab_environment(
    user: UserInfo,
    lab: LabSpecification,
    token: str,
    logger: BoundLogger = Depends(logger_dependency),
    api: api_client = Depends(corev1_api_dependency),
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
        events=[],
    )
    try:
        namespace = await _create_user_namespace(api, username)
        await _create_user_lab_objects(api, namespace, user, lab, token)
        await _create_user_lab_pod(api, namespace, user, lab)
    except Exception as e:
        labs[username].status = "failed"
        logger.error(f"User lab creation for {username} failed: {e}")
        raise
    # user creation was successful; drop events.
    labs[username].pod = "present"
    labs[username].events = []
    return


async def _create_user_namespace(
    api: api_client,
    username: str,
    logger: BoundLogger = Depends(logger_dependency),
) -> str:
    ns_name = get_user_namespace(username)
    try:
        await asyncio.wait_for(
            api.create_namespace(
                V1Namespace(metadata=get_std_metadata(name=ns_name))
            ),
            config.k8s_request_timeout,
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
            await delete_namespace(ns_name)
            # And just try again, and return *that* one's return code.
            return await (_create_user_namespace(api, username, logger))
        else:
            logger.exception(f"Failed to create namespace {ns_name}: {e}")
            raise
    return ns_name


async def _create_user_lab_objects(
    api: api_client,
    namespace: str,
    user: UserInfo,
    lab: LabSpecification,
    token: str,
) -> None:
    return


async def _create_user_lab_pod(
    api: api_client, namespace: str, user: UserInfo, lab: LabSpecification
) -> None:
    return
