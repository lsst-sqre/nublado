import asyncio
from collections import deque
from copy import copy

from aiojobs import Scheduler
from kubernetes_asyncio.client import ApiClient
from kubernetes_asyncio.client.models import V1Namespace, V1ObjectMeta
from kubernetes_asyncio.client.rest import ApiException
from structlog.stdlib import BoundLogger

from ..models.v1.domain.config import Config
from ..models.v1.external.userdata import (
    LabSpecification,
    UserData,
    UserInfo,
    UserMap,
)
from ..services.labels import std_annotations, std_labels
from ..services.quota import quota_from_size


class LabClient:
    def __init__(
        self,
        user: UserInfo,
        token: str,
        logger: BoundLogger,
        labs: UserMap,
        k8s_api: ApiClient,
        namespace: str,
        config: Config,
    ) -> None:
        self.user = user
        self.token = token
        self.logger = logger
        self.labs = labs
        self.k8s_api = k8s_api
        self.api = self.k8s_api("CoreV1Api")
        self.namespace = namespace
        self.config = config

    async def create_lab_environment(
        self,
        lab: LabSpecification,
    ) -> None:
        username = self.user.username
        self.labs[username] = UserData(
            username=username,
            status="starting",
            pod="missing",
            options=copy(lab.options),
            env=copy(lab.env),
            uid=self.user.uid,
            gid=self.user.gid,
            groups=copy(self.user.groups),
            quotas=quota_from_size(lab.options.size),
        )
        try:
            await self.create_user_namespace()
            await self.create_user_lab_objects(lab)
            await self.create_user_lab_pod(lab)
        except Exception as e:
            self.labs[username].status = "failed"
            self.logger.error(f"User lab creation for {username} failed: {e}")
            raise
        # user creation was successful; drop events.
        self.labs[username].pod = "present"
        self.labs[username].events = deque()
        return

    async def create_user_namespace(self) -> None:

        try:
            await asyncio.wait_for(
                self.api.create_namespace(
                    V1Namespace(
                        metadata=self.get_std_metadata(name=self.namespace)
                    )
                ),
                self.config.kubernetes.request_timeout,
            )
        except ApiException as e:
            if e.status == 409:
                self.logger.info(f"Namespace {self.namespace} already exists")
                # ... but we know that we don't have a lab for the user,
                # because we got this far.  So there's a stranded namespace,
                # and we should delete it and recreate it.
                #
                # The spec actually calls for us to delete the lab and then the
                # namespace, but let's just remove the namespace, which should
                # also clean up all its contents.
                await self.delete_namespace()
                # And just try again, and return *that* one's return code.
                return await self.create_user_namespace()
            else:
                self.logger.exception(
                    f"Failed to create namespace {self.namespace}: {e}"
                )
                raise
        return

    async def create_user_lab_objects(
        self,
        lab: LabSpecification,
    ) -> None:
        # Initially this will create all the resources in parallel.  If it
        # turns out we need to sequence that, we do this more manually with
        # explicit awaits.
        scheduler: Scheduler = Scheduler(
            close_timeout=self.config.kubernetes.request_timeout
        )
        await scheduler.spawn(
            self.create_secrets(
                lab=lab,
            )
        )
        await scheduler.spawn(
            self.create_nss(
                lab=lab,
            )
        )
        await scheduler.spawn(
            self.create_env(
                lab=lab,
            )
        )
        await scheduler.spawn(
            self.create_network_policy(
                lab=lab,
            )
        )
        await scheduler.spawn(
            self.create_quota(
                lab=lab,
            )
        )
        await scheduler.close()
        return

    async def create_secrets(
        self,
        lab: LabSpecification,
    ) -> None:
        return

    async def create_nss(
        self,
        lab: LabSpecification,
    ) -> None:
        return

    async def create_env(
        self,
        lab: LabSpecification,
    ) -> None:
        return

    async def create_network_policy(
        self,
        lab: LabSpecification,
    ) -> None:
        return

    async def create_quota(
        self,
        lab: LabSpecification,
    ) -> None:
        return

    async def create_user_lab_pod(
        self,
        lab: LabSpecification,
    ) -> None:
        return

    async def delete_lab_environment(
        self,
        username: str,
    ) -> None:
        # Clear Events for user:
        self.labs[username].events = deque()
        self.labs[username].status = "terminating"
        try:
            await self.delete_namespace()
        except Exception as e:
            self.logger.error(f"Could not delete lab environment: {e}")
            self.labs[username].status = "failed"
            raise
        del self.labs[username]

    async def delete_namespace(
        self,
    ) -> None:
        """Delete the namespace with name ``namespace``.  If it doesn't exist,
        that's OK.

        Exposed because create_lab may use it if the user namespace exists but
        we don't have a lab record.
        """
        try:
            await asyncio.wait_for(
                self.api.delete_namespace(self.namespace),
                self.config.kubernetes.request_timeout,
            )
        except ApiException as e:
            if e.status != 404:
                raise

    def get_std_metadata(self, name: str) -> V1ObjectMeta:
        return V1ObjectMeta(
            name=name, labels=std_labels(), annotations=std_annotations()
        )


class Watcher:
    pass  # use Russ's
