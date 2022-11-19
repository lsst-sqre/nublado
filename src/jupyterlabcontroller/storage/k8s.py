from __future__ import annotations

import asyncio
from copy import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, TypeAlias

from kubernetes_asyncio import client
from kubernetes_asyncio.client.api_client import ApiClient
from kubernetes_asyncio.client.models import (
    V1Affinity,
    V1ConfigMap,
    V1Container,
    V1ContainerImage,
    V1LocalObjectReference,
    V1Namespace,
    V1NetworkPolicy,
    V1NetworkPolicySpec,
    V1NodeAffinity,
    V1NodeSelector,
    V1NodeSelectorRequirement,
    V1NodeSelectorTerm,
    V1ObjectMeta,
    V1Pod,
    V1PodSecurityContext,
    V1PodSpec,
    V1ResourceQuota,
    V1ResourceQuotaSpec,
    V1Secret,
    V1Toleration,
    V1Volume,
)
from kubernetes_asyncio.client.rest import ApiException
from kubernetes_asyncio.watch import Watch
from structlog.stdlib import BoundLogger

from ..models.exceptions import NSCreationError
from ..models.v1.event import Event, EventQueue
from ..models.v1.lab import UserResourceQuantum


@dataclass
class ContainerImage:
    names: List[str]
    size_bytes: int

    @classmethod
    def from_v1_container_image(cls, img: V1ContainerImage) -> ContainerImage:
        return cls(names=copy(img.names), size_bytes=img.size_bytes)


@dataclass
class Secret:
    data: Dict[str, str]
    secret_type: str = "Opaque"


ContainerImageList: TypeAlias = List[ContainerImage]
NodeContainers: TypeAlias = Dict[str, ContainerImageList]


# FIXME
# For now these are just aliases, but we want to do what we did with
# ContainerImage above and create simplified versions of the objects
# with some defaults held constant.
NetworkPolicySpec: TypeAlias = V1NetworkPolicySpec
PodSpec: TypeAlias = V1PodSpec
Affinity: TypeAlias = V1Affinity
Container: TypeAlias = V1Container
LocalObjectReference: TypeAlias = V1LocalObjectReference
NodeAffinity: TypeAlias = V1NodeAffinity
NodeSelector: TypeAlias = V1NodeSelector
NodeSelectorRequirement: TypeAlias = V1NodeSelectorRequirement
NodeSelectorTerm: TypeAlias = V1NodeSelectorTerm
PodSecurityContext: TypeAlias = V1PodSecurityContext
Toleration: TypeAlias = V1Toleration
Volume: TypeAlias = V1Volume


class K8sStorageClient:
    def __init__(
        self, k8s_api: ApiClient, timeout: int, logger: BoundLogger
    ) -> None:
        self.k8s_api = k8s_api
        self.api = client.CoreV1Api(k8s_api)
        self.timeout = timeout
        self.logger = logger

    async def aclose(self) -> None:
        await self.k8s_api.close()

    def get_std_metadata(self, name: str) -> V1ObjectMeta:
        return V1ObjectMeta(
            name=name,
            labels={"argocd.argoproj.io/instance": "nublado-users"},
            annotations={
                "argocd.argoproj.io/compare-options": "IgnoreExtraneous",
                "argocd.argoproj.io/sync-options": "Prune=false",
            },
        )

    async def create_namespace(self, ns_name: str) -> None:
        try:
            await asyncio.wait_for(
                self.api.create_namespace(
                    V1Namespace(metadata=self.get_std_metadata(name=ns_name))
                ),
                self.timeout,
            )
        except ApiException as e:
            raise NSCreationError(e)

    async def create_secret(
        self,
        name: str,
        namespace: str,
        data: Dict[str, str],
        immutable: bool = True,
    ) -> None:
        #
        # FIXME: special-case "pull-secret"
        #
        secret = V1Secret(
            data=data,
            immutable=immutable,
            metadata=self.get_std_metadata(name),
        )
        await self.api.create_namespaced_secret(namespace, secret)
        return

    async def read_secret(
        self,
        name: str,
        namespace: str,
    ) -> Secret:
        secret: V1Secret = await self.api.read_namespaced_secret(
            name, namespace
        )
        secret_type = secret.type
        return Secret(data=secret.data, secret_type=secret_type)

    async def create_configmap(
        self,
        name: str,
        namespace: str,
        data: Dict[str, str],
        immutable: bool = True,
    ) -> None:
        configmap = V1ConfigMap(
            data=data,
            immutable=immutable,
            metadata=self.get_std_metadata(name="configmap"),
        )
        await self.api.create_namespaced_configmap(namespace, configmap)

    async def create_network_policy(
        self, name: str, namespace: str, spec: NetworkPolicySpec
    ) -> None:
        api = client.NetworkingV1Api(self.k8s_api)
        policy = V1NetworkPolicy(
            metadata=self.get_std_metadata(name),
            spec=spec,
        )
        await api.create_namespaced_network_policy(namespace, policy)

    async def create_quota(
        self,
        name: str,
        namespace: str,
        quota: UserResourceQuantum,
    ) -> None:
        quota_obj = V1ResourceQuota(
            metadata=self.get_std_metadata(name),
            spec=V1ResourceQuotaSpec(
                hard={
                    "limits": {
                        "cpu": str(quota.cpu),
                        "memory": str(quota.memory),
                    },
                }
            ),
        )
        await self.api.create_namespaced_resource_quota(namespace, quota_obj)

    async def create_pod(
        self, name: str, namespace: str, pod: PodSpec
    ) -> None:
        pod_obj = V1Pod(metadata=self.get_std_metadata(name), spec=pod)
        await self.api.create_namespaced_pod(namespace, pod_obj)

    async def delete_namespace(
        self,
        namespace: str,
    ) -> None:
        """Delete the namespace with name ``namespace``.  If it doesn't exist,
        that's OK.

        Exposed because create_lab may use it if the user namespace exists but
        we don't have a lab record.
        """
        try:
            await asyncio.wait_for(
                self.api.delete_namespace(namespace),
                self.timeout,
            )
        except ApiException as e:
            if e.status != 404:
                raise

    async def get_image_data(self) -> NodeContainers:
        resp = await self.api.list_node()
        all_images_by_node: NodeContainers = dict()
        for n in resp.items:
            nn = n.metadata.name
            all_images_by_node[nn] = list()
            for ci in n.status.images:
                all_images_by_node[nn].append(
                    ContainerImage.from_v1_container_image(ci)
                )
        return all_images_by_node


# Needs adaptation to our use case
class K8sWatcher:
    """Watch for cluster-wide changes to a custom resource.

    Parameters
    ----------
    plural : `str`
        The plural for the custom resource for which to watch.
    api_client : ``kubernetes_asyncio.client.ApiClient``
        The Kubernetes client.
    queue : `EventQueue`
        The queue into which to put the events.
    logger : `structlog.stdlib.BoundLogger`
        Logger to use for messages.
    """

    def __init__(
        self,
        plural: str,
        api_client: ApiClient,
        queue: EventQueue,
        logger: BoundLogger,
    ) -> None:
        self._plural = plural
        self._queue = queue
        self._logger = logger
        self._api = api_client

    async def run(self) -> None:
        """Watch for changes to the configured custom object.

        This method is intended to be run as a background async task.  It will
        run forever, adding any custom object changes to the associated queue.
        """
        self._logger.debug("Starting Kubernetes watcher")
        consecutive_failures = 0
        watch_call = (
            self._api.list_cluster_custom_object,
            "gafaelfawr.lsst.io",
            "v1alpha1",
            self._plural,
        )
        while True:
            try:
                async with Watch().stream(*watch_call) as stream:
                    async for raw_event in stream:
                        event = self._parse_raw_event(raw_event)
                        if event:
                            self._queue.append(event)
                        consecutive_failures = 0
            except ApiException as e:
                # 410 status code just means our watch expired, and the
                # correct thing to do is quietly restart it.
                if e.status == 410:
                    continue
                msg = "ApiException from watch"
                consecutive_failures += 1
                if consecutive_failures > 10:
                    raise
                else:
                    self._logger.exception(msg, error=str(e))
                    msg = "Pausing 10s before attempting to continue"
                    self._logger.info()
                    await asyncio.sleep(10)

    def _parse_raw_event(self, raw_event: Dict[str, Any]) -> Optional[Event]:
        """Parse a raw event from the watch API.

        Returns
        -------
        event : `Event` or `None`
            An `Event` object if the event could be parsed, otherwise
           `None`.
        """
        try:
            return Event(
                event=raw_event["type"],
                data=raw_event["object"]
                # namespace=raw_event["object"]["metadata"]["namespace"],
                # generation=raw_event["object"]["metadata"]["generation"],
            )
        except KeyError:
            return None
