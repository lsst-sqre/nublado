"""Kubernetes storage layer for the Nublado lab controller."""

from __future__ import annotations

import asyncio
from base64 import b64encode
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any, Optional

from kubernetes_asyncio import client, watch
from kubernetes_asyncio.client import (
    ApiClient,
    ApiException,
    V1ConfigMap,
    V1LabelSelector,
    V1Namespace,
    V1NetworkPolicy,
    V1NetworkPolicyIngressRule,
    V1NetworkPolicyPort,
    V1NetworkPolicySpec,
    V1ObjectMeta,
    V1OwnerReference,
    V1Pod,
    V1PodSpec,
    V1ResourceQuota,
    V1ResourceQuotaSpec,
    V1Secret,
    V1Service,
    V1ServicePort,
    V1ServiceSpec,
)
from structlog.stdlib import BoundLogger

from ..config import LabSecret
from ..exceptions import (
    KubernetesError,
    MissingSecretError,
    WaitingForObjectError,
)
from ..models.domain.kubernetes import (
    KubernetesNodeImage,
    KubernetesPodEvent,
    KubernetesPodPhase,
)
from ..models.k8s import Secret
from ..models.v1.lab import UserResourceQuantum
from ..util import deslashify

__all__ = ["K8sStorageClient"]


class K8sStorageClient:
    def __init__(
        self,
        *,
        kubernetes_client: ApiClient,
        timeout: int,
        spawn_timeout: timedelta,
        logger: BoundLogger,
    ) -> None:
        self.k8s_api = kubernetes_client
        self.api = client.CoreV1Api(kubernetes_client)
        self._timeout = timeout
        self._spawn_timeout = spawn_timeout
        self._logger = logger

    async def create_user_namespace(self, name: str) -> None:
        """Create the namespace for a user's lab.

        Parameters
        ----------
        name
            Name of the namespace.
        """
        self._logger.debug("Creating namespace", name=name)
        body = V1Namespace(metadata=self._standard_metadata(name))
        try:
            await self.api.create_namespace(body)
        except ApiException as e:
            if e.status == 409:
                # The namespace already exists. Presume that it is stranded,
                # delete it and all of its resources, and recreate it.
                await self._recreate_user_namespace(name)
            msg = "Error creating user namespace"
            raise KubernetesError.from_exception(msg, e, name=name) from e

    async def create_secrets(
        self,
        secret_list: list[LabSecret],
        username: str,
        token: str,
        source_ns: str,
        target_ns: str,
    ) -> None:
        data = await self.merge_controller_secrets(
            token, source_ns, secret_list
        )
        await self.create_secret(f"nb-{username}", target_ns, data)

    async def wait_for_namespace_deletion(
        self, namespace: str, interval: float = 0.2
    ) -> None:
        """Wait for a namespace to disappear.

        Once it's underway, we loop, reading the namespace. We eventually
        expect a 404, and when we get it we return. If it doesn't arrive
        within the timeout, we raise the timeout exception, and if we get some
        other error, we repackage that and raise it.
        """
        self._logger.debug("Waiting for namespace deletion", name=namespace)
        elapsed = 0.0
        while elapsed < self._timeout:
            try:
                await self.api.read_namespace(namespace)
            except ApiException as e:
                if e.status == 404:
                    return
                raise KubernetesError.from_exception(
                    "Cannot get status of namespace", e, name=namespace
                ) from e
            await asyncio.sleep(interval)
            elapsed += interval
        raise WaitingForObjectError("Timed out waiting for namespace deletion")

    async def remove_completed_pod(
        self, podname: str, namespace: str, interval: float = 0.2
    ) -> None:
        logger = self._logger.bind(name=podname, namespace=namespace)
        logger.debug("Waiting for pod execution to succeed")
        elapsed = 0.0
        pod_timeout = 30  # arbitrary, but the prepuller pod should just sleep
        # 5 seconds and go away.
        while elapsed < pod_timeout:
            try:
                pod = await self.api.read_namespaced_pod_status(
                    name=podname, namespace=namespace
                )  # Actually returns a V1Pod, not a V1PodStatus
                pod_status = pod.status
            except ApiException as e:
                if e.status == 404:
                    # Not there to start with is OK.
                    return
                else:
                    raise KubernetesError.from_exception(
                        "Error reading pod status of completed pod",
                        e,
                        namespace=namespace,
                        name=podname,
                    ) from e
            phase = pod_status.phase
            if phase == KubernetesPodPhase.SUCCEEDED:
                logger.debug("Removing succeeded pod")
                try:
                    await self.api.delete_namespaced_pod(podname, namespace)
                except ApiException as e:
                    if e.status == 404:
                        return
                    raise KubernetesError.from_exception(
                        "Error deleting completed pod",
                        e,
                        namespace=namespace,
                        name=podname,
                    ) from e
                return
            await asyncio.sleep(interval)
            elapsed += interval
        # And if we get this far, it timed out without being created.
        raise WaitingForObjectError(
            f"Timed out waiting for pod {namespace}/{podname} creation"
        )

    async def wait_for_pod(
        self, pod_name: str, namespace: str
    ) -> AsyncIterator[KubernetesPodEvent]:
        """Monitor the startup of a pod.

        Watches for events involving a pod, yielding them until the pod
        finishes starting up or fails.

        Parameters
        ----------
        pod_name
            Name of the pod.
        namespace
            Namespace in which the pod is located.

        Yields
        ------
        KubernetesPodEvent
            The next observed event and pod state.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        WaitingForObjectError
            Raised if the pod spawn doesn't succeed or fail within the
            timeout period.
        """
        logger = self._logger.bind(pod=pod_name, namespace=namespace)
        logger.debug("Watching pod events")
        w = watch.Watch()
        method = self.api.list_namespaced_event
        watch_args = {
            "namespace": namespace,
            "field_selector": f"involvedObject.name={pod_name}",
            "resource_version": "0",
            "timeout_seconds": int(self._spawn_timeout.total_seconds()),
            "_request_timeout": self._timeout,
        }
        try:
            async with w.stream(method, **watch_args) as stream:
                async for event in stream:
                    # Ideally we would use the parsed rather than the raw
                    # object and make use of the better Python models, but
                    # this doesn't seem to work with kubernetes_asyncio with
                    # our mock. This is probably a bug in the mock that we
                    # should fix, but use the raw object for now since it's
                    # not much harder.
                    raw_event = event["raw_object"]

                    # Parse the event, yield the results, and then break out
                    # of the loop if the pod reached a terminal state.
                    event = await self._handle_pod_event(
                        raw_event, pod_name, namespace, logger
                    )
                    if not event:
                        continue
                    yield event
                    if event.done:
                        w.stop()
                        break
        except ApiException as e:
            raise KubernetesError.from_exception(
                "Error watching pod startup",
                e,
                namespace=namespace,
                name=pod_name,
            ) from e

    async def _handle_pod_event(
        self,
        raw_event: dict[str, Any],
        name: str,
        namespace: str,
        logger: BoundLogger,
    ) -> KubernetesPodEvent | None:
        """Handle a single event seen while watching pod startup.

        Parameters
        ----------
        raw_event
            Kubernetes core event object as a dictionary.
        name
            Name of the pod being watched.
        namespace
            Namespace of the pod being watched.
        logger
            Bound logger with additional metadata to use for logging.

        Returns
        -------
        KubernetesPodEvent
            The parsed version of this event, including the current pod
            status, or `None` if there was no message in the event.

        Raises
        ------
        kubernetes_asyncio.client.ApiException
            Raised if an error occurred retrieving the pod status (other than
            404 for a missing pod, which is treated as a spawn failure).
        """
        message = raw_event.get("message")
        logger.debug(
            "Saw Kubernetes event",
            object=raw_event.get("involved_object"),
            message=message,
        )
        if not message:
            return None

        # Check to see if the pod has reached an end state (anything other
        # than Pending or Unknown).
        error = None
        try:
            pod = await self.api.read_namespaced_pod_status(name, namespace)
        except ApiException as e:
            if e.status == 404:
                error = "Pod disappeared while spawning"
                logger.error(error)
                phase = KubernetesPodPhase.FAILED
            else:
                raise
        else:
            phase = pod.status.phase

        # Log and return the results.
        if phase == KubernetesPodPhase.UNKNOWN:
            error = "Pod phase is Unknown, assuming it failed"
            logger.error(error)
        else:
            logger.debug(f"Pod phase is now {phase}")
        return KubernetesPodEvent(message=message, phase=phase, error=error)

    async def copy_secret(
        self,
        *,
        source_namespace: str,
        source_secret: str,
        target_namespace: str,
        target_secret: str,
    ) -> None:
        """Copy a Kubernetes secret from one namespace to another.

        Parameters
        ----------
        source_namespace
            Namespace of source secret.
        source_secret
            Name of source secret.
        target_namespace
            Namespace to which to copy the secret.
        target_secret
            Name of secret to create.
        """
        secret = await self.read_secret(source_secret, source_namespace)
        await self.create_secret(
            name=target_secret,
            namespace=target_namespace,
            data=secret.data,
            secret_type=secret.secret_type,
        )

    async def merge_controller_secrets(
        self, token: str, source_namespace: str, secret_list: list[LabSecret]
    ) -> dict[str, str]:
        """Create a user lab secret, merging together multiple data sources.

        Parameters
        ----------
        token
            User's Gafaelfawr token.
        source_namespace
            Source namespace for additional secrets.
        secret_list
            List of additional secrets to pull from the source namespace.

        Returns
        -------
        dict of str to str
            Base64-encoded secret data suitable for the ``data`` key of a
            ``V1Secret`` Kubernetes object.
        """
        data = {"token": b64encode(token.encode()).decode()}

        # Minor optimization: gather the name of all of our source secrets so
        # that we only have to read each one once.
        secret_names = [s.secret_name for s in secret_list]
        secret_data = {}
        for secret_name in secret_names:
            secret = await self.read_secret(secret_name, source_namespace)
            secret_data[secret_name] = secret.data

        # Now, construct the data for the user's lab secret.
        for spec in secret_list:
            key = spec.secret_key
            if key not in secret_data[spec.secret_name]:
                name = f"{source_namespace}/{spec.secret_name}"
                raise MissingSecretError(f"No key {key} in {name}")
            if key in data:
                # Should be impossible due to the validator on our
                # configuration, which should check for conflicts.
                raise RuntimeError(f"Duplicate secret key {key}")
            data[key] = secret_data[spec.secret_name][key]

        # Return the results.
        return data

    async def create_secret(
        self,
        name: str,
        namespace: str,
        data: dict[str, str],
        secret_type: str = "Opaque",
        immutable: bool = True,
    ) -> None:
        secret = V1Secret(
            data=data,
            type=secret_type,
            immutable=immutable,
            metadata=self._standard_metadata(name),
        )
        self._logger.debug("Creating secret", name=name, namespace=namespace)
        try:
            await self.api.create_namespaced_secret(namespace, secret)
        except ApiException as e:
            raise KubernetesError.from_exception(
                "Error creating secret", e, namespace=namespace, name=name
            ) from e

    async def read_secret(
        self,
        name: str,
        namespace: str,
    ) -> Secret:
        logger = self._logger.bind(name=name, namespace=namespace)
        logger.debug("Reading secret")
        try:
            secret = await self.api.read_namespaced_secret(name, namespace)
        except ApiException as e:
            if e.status == 404:
                logger.error("Secret does not exist")
                msg = f"Secret {namespace}/{name} does not exist"
                raise MissingSecretError(msg)
            else:
                raise KubernetesError.from_exception(
                    "Error reading secret", e, namespace=namespace, name=name
                ) from e
        secret_type = secret.type
        return Secret(data=secret.data, secret_type=secret_type)

    async def create_configmap(
        self,
        name: str,
        namespace: str,
        data: dict[str, str],
        immutable: bool = True,
    ) -> None:
        self._logger.debug(
            "Creating config map", name=name, namespace=namespace
        )
        configmap = V1ConfigMap(
            data={deslashify(k): v for k, v in data.items()},
            immutable=immutable,
            metadata=self._standard_metadata(name),
        )
        try:
            await self.api.create_namespaced_config_map(namespace, configmap)
        except ApiException as e:
            raise KubernetesError.from_exception(
                "Error creating config map", e, namespace=namespace, name=name
            ) from e

    async def create_network_policy(
        self,
        name: str,
        namespace: str,
    ) -> None:
        api = client.NetworkingV1Api(self.k8s_api)
        self._logger.debug(
            "Creating network policy", name=name, namespace=namespace
        )
        # FIXME we need to further restrict Ingress to the right pods,
        # and Egress to ... external world, Hub, Portal, Gafaelfawr.  What
        # else?
        policy = V1NetworkPolicy(
            metadata=self._standard_metadata(name),
            spec=V1NetworkPolicySpec(
                policy_types=["Ingress"],
                pod_selector=V1LabelSelector(
                    match_labels={"app": "jupyterhub", "component": "hub"}
                ),
                ingress=[
                    V1NetworkPolicyIngressRule(
                        ports=[V1NetworkPolicyPort(port=8888)],
                    ),
                ],
            ),
        )
        try:
            await api.create_namespaced_network_policy(namespace, policy)
        except ApiException as e:
            raise KubernetesError.from_exception(
                "Error creating network policy",
                e,
                namespace=namespace,
                name=name,
            ) from e

    async def create_lab_service(self, username: str, namespace: str) -> None:
        self._logger.debug("Creating service", name="lab", namespace=namespace)
        service = V1Service(
            metadata=self._standard_metadata("lab"),
            spec=V1ServiceSpec(
                ports=[V1ServicePort(port=8888, target_port=8888)],
                selector={"app": "lab"},
            ),
        )
        try:
            await self.api.create_namespaced_service(namespace, service)
        except ApiException as e:
            raise KubernetesError.from_exception(
                "Error creating service",
                e,
                namespace=namespace,
                name="lab",
            ) from e

    async def create_quota(
        self,
        name: str,
        namespace: str,
        resource: UserResourceQuantum,
    ) -> None:
        self._logger.debug(
            "Creating resource quota", name=name, namespace=namespace
        )
        quota = V1ResourceQuota(
            metadata=self._standard_metadata(name),
            spec=V1ResourceQuotaSpec(
                hard={
                    "limits.cpu": str(resource.cpu),
                    "limits.memory": str(resource.memory),
                }
            ),
        )
        try:
            await self.api.create_namespaced_resource_quota(namespace, quota)
        except ApiException as e:
            raise KubernetesError.from_exception(
                "Error creating resource quota",
                e,
                namespace=namespace,
                name=name,
            ) from e

    async def create_pod(
        self,
        name: str,
        namespace: str,
        pod_spec: V1PodSpec,
        *,
        labels: Optional[dict[str, str]] = None,
        annotations: Optional[dict[str, str]] = None,
        owner: Optional[V1OwnerReference] = None,
    ) -> None:
        self._logger.debug("Creating pod", name=name, namespace=namespace)
        metadata = self._standard_metadata(name)
        if labels:
            metadata.labels.update(labels)
        if annotations:
            metadata.annotations.update(annotations)
        if owner:
            metadata.owner_references = [owner]
        pod = V1Pod(metadata=metadata, spec=pod_spec)
        try:
            await self.api.create_namespaced_pod(namespace, pod)
        except ApiException as e:
            raise KubernetesError.from_exception(
                "Error creating pod",
                e,
                namespace=namespace,
                name=name,
            ) from e

    async def delete_namespace(self, name: str) -> None:
        """Delete the namespace with name ``name``.  If it doesn't exist,
        that's OK.
        """
        self._logger.debug("Deleting namespace", name=name)
        try:
            await asyncio.wait_for(
                self.api.delete_namespace(name), self._timeout
            )
        except ApiException as e:
            if e.status == 404:
                return
            msg = "Error deleting namespace"
            raise KubernetesError.from_exception(msg, e, name=name) from e
        except TimeoutError:
            msg = (
                f"Timed out after {self._timeout}s waiting for namespace"
                f" {name} to be deleted"
            )
            raise WaitingForObjectError(msg)

    async def get_image_data(self) -> dict[str, list[KubernetesNodeImage]]:
        """Get the list of cached images from each node.

        Returns
        -------
        dict of str to list
            Map of nodes to lists of all cached images on that node.
        """
        self._logger.debug("Getting node image data")
        try:
            nodes = await self.api.list_node()
        except ApiException as e:
            msg = "Error reading node information"
            raise KubernetesError.from_exception(msg, e)
        image_data = {}
        for node in nodes.items:
            name = node.metadata.name
            images = [
                KubernetesNodeImage.from_container_image(i)
                for i in node.status.images
            ]
            image_data[name] = images
        return image_data

    async def get_config_map(
        self, name: str, namespace: str
    ) -> V1ConfigMap | None:
        """Read a ``ConfigMap`` object from Kubernetes.

        Parameters
        ----------
        name
            Name of the config map.
        namespace
            Namespace of the config map.

        Returns
        -------
        kubernetes_asyncio.client.V1ConfigMap or None
            The ``ConfigMap`` object, or `None` if it does not exist.

        Raises
        ------
        KubernetesError
            Raised if a Kubernetes API call fails.
        """
        try:
            return await self.api.read_namespaced_config_map(name, namespace)
        except ApiException as e:
            if e.status == 404:
                return None
            raise KubernetesError.from_exception(
                "Error reading config map", e, namespace=namespace, name=name
            ) from e

    async def get_pod(self, name: str, namespace: str) -> V1Pod | None:
        """Read a ``Pod`` object from Kubernetes.

        Parameters
        ----------
        name
            Name of the pod.
        namespace
            Namespace of the pod.

        Returns
        -------
        kubernetes_asyncio.client.V1Pod or None
            The ``Pod`` object, or `None` if it does not exist.

        Raises
        ------
        KubernetesError
            Raised if a Kubernetes API call fails.
        """
        try:
            return await self.api.read_namespaced_pod(name, namespace)
        except ApiException as e:
            if e.status == 404:
                return None
            raise KubernetesError.from_exception(
                "Error reading pod", e, namespace=namespace, name=name
            ) from e

    async def get_pod_phase(
        self, name: str, namespace: str
    ) -> KubernetesPodPhase | None:
        """Get the phase of a currently running pod.

        Called whenever JupyterHub wants to check the status of running pods,
        so this will be called frequently and should be fairly quick.

        Parameters
        ----------
        name
            Name of the pod.
        namespace
            Namespace of the pod

        Returns
        -------
        KubernetesPodPhase or None
            Phase of the pod or `None` if the pod does not exist.

        Raises
        ------
        KubernetesError
            Raised on failure to talk to Kubernetes.
        """
        msg = "Getting pod status"
        self._logger.debug(msg, name=name, namespace=namespace)
        try:
            pod = await self.api.read_namespaced_pod_status(name, namespace)
        except ApiException as e:
            if e.status == 404:
                return None
            raise KubernetesError.from_exception(
                "Error reading pod status", e, namespace=namespace, name=name
            ) from e
        return pod.status.phase

    async def get_quota(
        self, name: str, namespace: str
    ) -> V1ResourceQuota | None:
        """Read a ``ResourceQuota`` object from Kubernetes.

        Parameters
        ----------
        name
            Name of the resource quota.
        namespace
            Namespace of the resource quota.

        Returns
        -------
        kubernetes_asyncio.client.V1ResourceQuota or None
            The ``ResourceQuota`` object, or `None` if it does not exist.

        Raises
        ------
        KubernetesError
            Raised if a Kubernetes API call fails.
        """
        api = self.api
        try:
            return await api.read_namespaced_resource_quota(name, namespace)
        except ApiException as e:
            if e.status == 404:
                return None
            raise KubernetesError.from_exception(
                "Error reading resource quota",
                e,
                namespace=namespace,
                name=name,
            ) from e

    async def list_namespaces(self, prefix: str) -> list[str]:
        """List namespaces with the given prefix.

        Parameters
        ----------
        prefix
            Prefix of namespaces of interest. A dash (``-``) will be added.

        Returns
        -------
        list of str
            List of namespaces whose names start with that prefix.

        Raises
        ------
        KubernetesError
            Raised if a Kubernetes API call fails.
        """
        try:
            namespaces = await self.api.list_namespace()
            return [
                n.metadata.name
                for n in namespaces.items
                if n.metadata.name.startswith(f"{prefix}-")
            ]
        except KubernetesError as e:
            msg = "Error listing namespaces"
            raise KubernetesError.from_exception(msg, e) from e

    async def _recreate_user_namespace(self, name: str) -> None:
        """Recreate an existing user namespace.

        The namespace for the user already exists. Delete it and recreate it.

        Parameters
        ----------
        name
            Name of the namespace.

        Raises
        ------
        KubernetesError
            Raised if Kubernetes API calls fail unexpectedly.
        """
        self._logger.warning(f"Namespace {name} already exists, removing")
        try:
            self.api.delete_namespace(name)
        except ApiException as e:
            if e.status != 404:
                msg = "Cannot delete stranded user namespace"
                raise KubernetesError.from_exception(msg, e, name=name) from e
        await self.wait_for_namespace_deletion(name)

        # Try to create it again. If it still conflicts, don't catch that
        # error; something weird is going on.
        namespace = V1Namespace(metadata=self._standard_metadata(name))
        try:
            await self.api.create_namespace(namespace)
        except ApiException as e:
            msg = "Cannot create user namespace"
            raise KubernetesError.from_exception(msg, e, name=name) from e

    def _standard_metadata(self, name: str) -> V1ObjectMeta:
        """Create the standard metadata for an object.

        Parameters
        ----------
        name
            Name of the object.

        Returns
        -------
        V1ObjectMeta
            Metadata for the object. Primarily, this adds the Argo CD
            annotations to make user labs play somewhat nicely with Argo CD.
        """
        return V1ObjectMeta(
            name=name,
            labels={"argocd.argoproj.io/instance": "nublado-users"},
            annotations={
                "argocd.argoproj.io/compare-options": "IgnoreExtraneous",
                "argocd.argoproj.io/sync-options": "Prune=false",
            },
        )
