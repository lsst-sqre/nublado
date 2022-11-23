from __future__ import annotations

import asyncio
import base64
from typing import Any, Dict, List, Optional, TypeAlias

from kubernetes_asyncio import client
from kubernetes_asyncio.client.api_client import ApiClient
from kubernetes_asyncio.client.models import (
    V1Affinity,
    V1ConfigMap,
    V1Container,
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

from ..config import LabSecret
from ..models.exceptions import (
    KubernetesError,
    NSCreationError,
    WaitingForObjectError,
    WatchError,
)
from ..models.k8s import (
    ContainerImage,
    NodeContainers,
    ObjectOperation,
    Secret,
)
from ..models.v1.event import Event, EventQueue
from ..models.v1.lab import UserResourceQuantum

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

    async def create_user_namespace(self, namespace: str) -> None:
        self.logger.info(f"Attempting creation of namespace '{namespace}'")
        try:
            await self._k8s_create_namespace(namespace)
        except ApiException as e:
            if e.status == 409:
                self.logger.info(f"Namespace {namespace} already exists")
                # ... but we know that we don't have a lab for the user,
                # because we got this far.  So there's a stranded namespace,
                # and we should delete it and recreate it.
                #
                # The spec actually calls for us to delete the lab and then the
                # namespace, but let's just remove the namespace, which should
                # also clean up all its contents.
                await self.delete_namespace(namespace)
                # Just try again, and return *that* one's return value.
                return await self.create_user_namespace(namespace)
            else:
                estr = f"Failed to create namespace {namespace}: {e}"
                self.logger.exception(estr)
                raise NSCreationError(estr)
        # We don't want to give control back until the namespace exists,
        # because the next step will be creating objects in that namespace.
        await self._wait_for_operation(
            namespace=namespace,
            item="namespace",
            operation=ObjectOperation.CREATION,
            interval=0.2,
        )

    async def _k8s_create_namespace(self, ns_name: str) -> None:
        await asyncio.wait_for(
            self.api.create_namespace(
                V1Namespace(metadata=self.get_std_metadata(name=ns_name))
            ),
            self.timeout,
        )

    async def create_secrets(
        self,
        secret_list: List[LabSecret],
        username: str,
        token: str,
        source_ns: str,
        target_ns: str,
    ) -> None:
        pull_secrets = [
            x for x in secret_list if x.secret_name == "pull_secret"
        ]
        secrets = [x for x in secret_list if x.secret_name != "pull_secret"]
        data = await self.merge_controller_secrets(
            secret_list=secrets, token=token, source_ns=source_ns
        )
        await self.create_secret(
            name=f"nb-{username}",
            namespace=target_ns,
            data=data,
        )
        if pull_secrets:
            pull_secret = await self.copy_pull_secret(source_ns=source_ns)
            await self.create_secret(
                name="pull-secret",
                namespace=target_ns,
                data=pull_secret,
                secret_type="kubernetes.io/dockerconfigjson",
            )
            # We are going to use the existence of the pull secret when
            # we create the pod in order to tell whether we should patch
            # in imagePullSecrets.  So we need to wait for it to show
            # up before we move on to the pod creation part.
            await self._wait_for_operation(
                namespace=target_ns,
                item="pull-secret",
                operation=ObjectOperation.CREATION,
                interval=0.2,
            )
        return

    async def _wait_for_operation(
        self,
        namespace: str,
        item: str,
        operation: ObjectOperation,
        interval: float,
    ) -> None:
        # asyncio.timeout() doesn't appear until Python 3.11 :-(
        thangs = {
            "pull-secret": self.api.read_namespaced_secret(
                "pull-secret", namespace
            ),
            "namespace": self.api.read_namespace(namespace),
        }

        thang = thangs.get(item)
        if thang is None:
            raise RuntimeError("Don't know how to wait for {item} {operation}")
        elapsed = 0.0
        while elapsed < self.timeout:
            errored = False
            try:
                await asyncio.wait_for(
                    thang,
                    self.timeout,
                )
                return
            except ApiException as e:
                if e.status != 404:
                    if operation == ObjectOperation.DELETION:
                        return
                    raise WaitingForObjectError(str(e))
                errored = True
            if not errored and operation == ObjectOperation.CREATION:
                return
            # If we're here, it's a delete, and the read didn't get an
            # error, or it's a creation and we did get an error, so we
            # need to wait and then retry
            await asyncio.sleep(interval)
            elapsed += interval
        raise asyncio.TimeoutError(
            f"Timeout while waiting for {item} {operation}"
        )

    async def copy_pull_secret(self, source_ns: str) -> Dict[str, str]:
        secret = await self.read_secret(
            name="pull-secret", namespace=source_ns
        )
        return secret.data

    async def merge_controller_secrets(
        self, secret_list: List[LabSecret], token: str, source_ns: str
    ) -> Dict[str, str]:
        """Merge the user token with whatever secrets we're injecting
        from the lab controller environment."""
        secret_names: List[str] = list()
        secret_keys: List[str] = list()
        for sec in secret_list:
            secret_names.append(sec.secret_name)
            if sec.secret_key in secret_keys:
                raise RuntimeError("Duplicate secret key {sec.secret_key}")
            secret_keys.append(sec.secret_key)
        # In theory, we should parallelize the secret reads.  But in practice
        # it makes life a lot more complex, and we probably just have one,
        # the controller secret.  Pull-secret will be handled separately.
        base64_data: Dict[str, str] = dict()
        for name in secret_names:
            secret: Secret = await self.read_secret(
                name=name, namespace=source_ns
            )
            # Retrieve matching keys
            for key in secret.data:
                if key in secret_keys:
                    base64_data[key] = secret.data[key]
        # There's no point in decoding it; all we're gonna do is pass it
        # down to create a secret as base64 anyway.
        if "token" in base64_data:
            raise RuntimeError("'token' must come from the user token")
        if not token:
            raise RuntimeError("User token cannot be empty")
        base64_data["token"] = str(base64.b64encode(token.encode("utf-8")))
        return base64_data

    async def create_secret(
        self,
        name: str,
        namespace: str,
        data: Dict[str, str],
        secret_type: str = "Opaque",
        immutable: bool = True,
    ) -> None:
        secret = V1Secret(
            data=data,
            type=secret_type,
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
        # Here's where we handle pull secrets.  We look for a secret named
        # "pull-secret" in the target namespace, and if it exists, we jam it
        # into the PodSpec.  That's why we had to wait for pull-secret
        # creation in the namespace-resource-creation step.
        pull_secret = True
        try:
            _ = self.api.read_namespaced_secret(
                "pull-secret", namespace=namespace
            )
        except ApiException as e:
            if e.status != 404:
                raise KubernetesError(f"{e} [status {e.status}]")
            pull_secret = False
        if pull_secret:
            pod.image_pull_secrets = [{"name": "pull-secret"}]
        pod_obj = V1Pod(metadata=self.get_std_metadata(name), spec=pod)
        await self.api.create_namespaced_pod(namespace=namespace, body=pod_obj)

    async def delete_namespace(
        self,
        namespace: str,
    ) -> None:
        """Delete the namespace with name ``namespace``.  If it doesn't exist,
        that's OK.

        We send the deletion.  Once it's underway, we loop, reading the
        namespace.  We eventually expect a 404, and when we get it we
        return.  If it doesn't arrive within the timeout, we raise the
        timeout exception, and if we get some other error, we repackage that
        and raise it.
        """
        await asyncio.wait_for(
            self.api.delete_namespace(namespace),
            self.timeout,
        )
        await self._wait_for_operation(
            namespace=namespace,
            item="namespace",
            operation=ObjectOperation.DELETION,
            interval=2.0,
        )

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
                    raise WatchError("Too many consecutive watch failures.")
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
