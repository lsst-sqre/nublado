"""Kubernetes storage layer for the Nublado lab controller."""

from __future__ import annotations

import asyncio
from base64 import b64encode
from collections.abc import AsyncIterator
from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable, Coroutine, Optional

from kubernetes_asyncio import client, watch
from kubernetes_asyncio.client import (
    ApiClient,
    ApiException,
    V1ConfigMap,
    V1Job,
    V1LabelSelector,
    V1Namespace,
    V1NetworkPolicy,
    V1NetworkPolicyIngressRule,
    V1NetworkPolicyPort,
    V1NetworkPolicySpec,
    V1ObjectMeta,
    V1OwnerReference,
    V1PersistentVolumeClaim,
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
from ..exceptions import KubernetesError, MissingObjectError, UnknownKindError
from ..models.domain.kubernetes import (
    KubernetesNodeImage,
    KubernetesPodEvent,
    KubernetesPodPhase,
)
from ..models.v1.lab import UserResourceQuantum
from ..util import deslashify

__all__ = ["K8sStorageClient"]


@dataclass
class EventData:
    type: str
    involved_object: dict[str, Any]
    name: str
    kind: str

    @classmethod
    def from_event(cls, event: dict[str, Any]) -> EventData:
        e_type = event["type"]  # If there's no type, it's OK to blow up.
        involved_obj = {}
        try:
            involved_obj = event["raw_object"]
        except KeyError:
            pass
        # extract kind from object
        try:
            kind = involved_obj["kind"]
        except KeyError:
            kind = "<unknown kind>"
        # extract name from object
        try:
            obj_name = involved_obj["metadata"]["name"]
        except (KeyError, TypeError):
            obj_name = "<unknown name>"
        return cls(
            type=e_type, involved_object=involved_obj, name=obj_name, kind=kind
        )


class K8sStorageClient:
    """
    Notes
    -----
    It's really tempting to create generic methods for object
    creation and deletion, that do some fancy exception handling to do
    retries and ignore error-cases-that-are-normal-operation,
    especially since Kubernetes methods are regular in both names and
    argument type and ordering, and we want to do very similar things
    for many objects.

    How hard could it be, you think, to use getattr() to pluck the
    right method, and then reuse the guts of creation/retry code?  And
    then you realize that you could do this to await the creation of
    an arbitrary Kubernetes object also.

    I am here to warn you, dear reader, that this turns out to be a
    terrible idea, because it turns errors you could have caught
    quickly and easily with the type system into runtime errors deep
    in the FastAPI event loop, with no obvious way to connect the
    stack trace back to the place you forgot an "await" or misspelled
    a method name."""

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
        self.batch_api = client.BatchV1Api(kubernetes_client)
        self.custom_api = client.CustomObjectsApi(kubernetes_client)
        self.networking_api = client.NetworkingV1Api(kubernetes_client)
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
        body = V1Namespace(metadata=self.standard_metadata(name))
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
        await self.create_secret(f"{username}-nb", target_ns, data)

    async def wait_for_namespace_deletion(
        self, namespace: str, interval: float = 0.2
    ) -> None:
        """Wait for a namespace to disappear.

        Once it's underway, we loop, reading the namespace. We eventually
        expect a 404, and when we get it we return. If it doesn't arrive
        within the timeout, we raise the timeout exception, and if we get some
        other error, we repackage that and raise it.

        Raises
        ------
        TimeoutError
            Raised if the namespace doesn't disappear within the configured
            timeout.
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
        raise TimeoutError("Timed out waiting for namespace deletion")

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
            if phase not in (
                KubernetesPodPhase.PENDING,
                KubernetesPodPhase.RUNNING,
            ):
                if phase == KubernetesPodPhase.SUCCEEDED:
                    logger.debug("Removing succeeded pod")
                else:
                    logger.warning(f"Removing pod in phase {phase}")
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
        raise TimeoutError(
            f"Timed out waiting for pod {namespace}/{podname} creation"
        )

    async def wait_for_pod(
        self, pod_name: str, namespace: str
    ) -> KubernetesPodPhase | None:
        """Waits for a pod to finish starting.

        Waits for the pod to reach a phase other than pending or unknown, and
        returns the new phase. We treat unknown like pending since we're
        running with a timeout anyway, and will eventually time out if we
        can't get back access to the node where the pod is running.

        Parameters
        ----------
        pod_name
            Name of the pod.
        namespace
            Namespace in which the pod is located.

        Returns
        -------
        KubernetesPodPhase
            New pod phase, or `None` if the pod has disappeared.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        logger = self._logger.bind(name=pod_name, namespace=namespace)
        logger.debug("Waiting for pod creation")
        initial_phase = "Pending"
        while True:
            # We only loop waiting for "Unknown" to resolve.
            phase = await self._pod_watch_loop(
                pod_name, namespace, initial_phase=initial_phase
            )
            if phase is None:
                return None
            if phase == KubernetesPodPhase.UNKNOWN:
                initial_phase = "Unknown"
                continue
            return phase

    async def watch_pod_events(
        self, pod_name: str, namespace: str
    ) -> AsyncIterator[str]:
        """Monitor the startup of a pod.

        Watches for events involving a pod, yielding them. Must be cancelled
        by the caller when the watch is no longer of interest.

        Parameters
        ----------
        pod_name
            Name of the pod.
        namespace
            Namespace in which the pod is located.

        Yields
        ------
        str
            The next observed event.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        logger = self._logger.bind(pod=pod_name, namespace=namespace)
        logger.debug("Watching pod events")
        method = self.api.list_namespaced_event
        watch_args = {
            "namespace": namespace,
            "field_selector": f"involvedObject.name={pod_name}",
        }
        field = ["message"]
        async for msg in self._inner_watch_streaming_loop(
            method=method,
            watch_args=watch_args,
            namespace=namespace,
            field=field,
        ):
            yield str(msg)

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
            The parsed version of this event.

        Raises
        ------
        kubernetes_asyncio.client.ApiException
            Raised if an error occurred retrieving the pod status (other than
            404 for a missing pod, which is treated as a spawn failure).
        """
        message = raw_event.get("message")
        logger.debug("Saw Kubernetes event", message=message)
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
        elif phase != KubernetesPodPhase.PENDING:
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
            secret_type=secret.type,
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
                raise MissingObjectError(
                    f"No key {key} in secret {name}",
                    kind="Secret",
                    name=spec.secret_name,
                    namespace=source_namespace,
                )
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
            metadata=self.standard_metadata(name, namespace=namespace),
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
    ) -> V1Secret:
        logger = self._logger.bind(name=name, namespace=namespace)
        logger.debug("Reading secret")
        try:
            return await self.api.read_namespaced_secret(name, namespace)
        except ApiException as e:
            if e.status == 404:
                logger.error("Secret does not exist")
                raise MissingObjectError(
                    message=f"Secret {namespace}/{name} does not exist",
                    kind="Secret",
                    name=name,
                    namespace=namespace,
                )
            else:
                raise KubernetesError.from_exception(
                    "Error reading secret", e, namespace=namespace, name=name
                ) from e

    async def create_pvcs(
        self, pvcs: list[V1PersistentVolumeClaim], namespace: str
    ) -> None:
        for pvc in pvcs:
            name = pvc.metadata.name
            pvc.metadata = self._standard_metadata(name)
            try:
                await self.api.create_namespaced_persistent_volume_claim(
                    namespace, pvc
                )
            except ApiException as e:
                raise KubernetesError.from_exception(
                    "Error creating PVC", e, namespace=namespace, name=name
                ) from e

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
            metadata=self.standard_metadata(name, namespace=namespace),
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
        api = self.networking_api
        self._logger.debug(
            "Creating network policy", name=name, namespace=namespace
        )
        # FIXME we need to further restrict Ingress to the right pods,
        # and Egress to ... external world, Hub, Portal, Gafaelfawr.  What
        # else?
        policy = V1NetworkPolicy(
            metadata=self.standard_metadata(name, namespace=namespace),
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
            metadata=self.standard_metadata("lab", namespace=namespace),
            spec=V1ServiceSpec(
                ports=[V1ServicePort(port=8888, target_port=8888)],
                selector={
                    "nublado.lsst.io/user": username,
                    "nublado.lsst.io/category": "lab",
                },
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
            metadata=self.standard_metadata(name, namespace=namespace),
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
        username: str = "",
        category: str = "lab",
        labels: Optional[dict[str, str]] = None,
        annotations: Optional[dict[str, str]] = None,
        owner: Optional[V1OwnerReference] = None,
        remove_on_conflict: bool = False,
    ) -> None:
        """Create a new Kubernetes pod.

        Parameters
        ----------
        name
            Name of the pod.
        namespace
            Namespace of the pod.
        pod_spec
            ``spec`` portion of the pod.
        username
            If set, user the pod is for.
        category
            If set, category for the pod (default "lab")
        labels
            Additional labels to add to the pod.
        annotations
            Additional annotations to add to the pod.
        owner
            If set, add this owner reference.
        remove_on_conflict
            If `True` and another pod already exists with the same name,
            delete it before creating this pod.
        """
        logger = self._logger.bind(name=name, namespace=namespace)
        logger.debug("Creating pod")
        metadata = self.standard_metadata(
            name, namespace=namespace, username=username, category=category
        )
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
            if e.status == 409 and remove_on_conflict:
                logger.warning("Pod already exists, removing")
                await self.delete_pod(name, namespace)
                try:
                    await self.api.create_namespaced_pod(namespace, pod)
                except ApiException as nested_exc:
                    e = nested_exc
                else:
                    return
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
            async with asyncio.timeout(self._timeout):
                await self.api.delete_namespace(name)
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
            raise TimeoutError(msg)

    async def delete_pod(self, name: str, namespace: str) -> None:
        """Delete a pod.

        Parameters
        ----------
        name
            Name of the pod.
        namespace
            Namespace of the pod.

        Raises
        ------
        KubernetesError
            Raised if there is a Kubernetes API error.
        """
        try:
            await self.api.delete_namespaced_pod(name, namespace)
        except ApiException as e:
            if e.status == 404:
                return
            raise KubernetesError.from_exception(
                "Error deleting pod", e, namespace=namespace, name=name
            ) from e

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
        try:
            pod = await self.api.read_namespaced_pod_status(name, namespace)
        except ApiException as e:
            if e.status == 404:
                msg = "Pod does not exist when checking phase"
                self._logger.debug(msg, name=name, namespace=namespace)
                return None
            raise KubernetesError.from_exception(
                "Error reading pod phase", e, namespace=namespace, name=name
            ) from e
        msg = f"Pod phase is {pod.status.phase}"
        self._logger.debug(msg, name=name, namespace=namespace)
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
        namespace = V1Namespace(metadata=self.standard_metadata(name))
        try:
            await self.api.create_namespace(namespace)
        except ApiException as e:
            msg = "Cannot create user namespace"
            raise KubernetesError.from_exception(msg, e, name=name) from e

    def standard_metadata(
        self,
        name: str,
        namespace: str = "",
        category: str = "lab",
        username: str = "",
    ) -> V1ObjectMeta:
        """Create the standard metadata for an object.

        Parameters
        ----------
        name
            Name of the object.

        namespace
            Namespace of the object (optional, defaults to the empty string).

        category
            Category of the object (optional, defaults to ``lab``).

        username
            User for whom the object is created (optional, defaults to
            the empty string).

        Returns
        -------
        V1ObjectMeta
            Metadata for the object. For labs, this primarily adds Argo CD
            annotations to make user labs play somewhat nicely with Argo CD.
            For fileservers, this also adds labels we can use as selectors;
            this is necessary because all user fileservers run in a single
            namespace.
        """
        argo_app = "nublado-users"
        if category == "fileserver":
            argo_app = "fileservers"
        elif category == "prepuller":
            argo_app = namespace or "prepuller"
        labels = {
            "argocd.argoproj.io/instance": argo_app,
            "nublado.lsst.io/category": category,
        }
        if username:
            labels["nublado.lsst.io/user"] = username
        annotations = {
            "argocd.argoproj.io/compare-options": "IgnoreExtraneous",
            "argocd.argoproj.io/sync-options": "Prune=false",
        }
        metadata = V1ObjectMeta(
            name=name,
            labels=labels,
            annotations=annotations,
        )
        if namespace:
            metadata.namespace = namespace
        return metadata

    # Methods for fileserver

    async def check_namespace(self, namespace: str) -> bool:
        """Check to see if namespace is present; return True if it is,
        False if it is not."""
        try:
            await self.api.read_namespace(namespace)
            return True
        except ApiException as e:
            if e.status != 404:
                msg = f"Cannot read namespace {namespace}"
                raise KubernetesError.from_exception(
                    msg, e, namespace=namespace
                ) from e
            return False

    async def create_fileserver_job(
        self, username: str, namespace: str, job: V1Job
    ) -> None:
        """For all of our fileserver objects: if we are being asked to
        create them, it means we thought, based on our user map, that we did
        not have a working fileserver.  If we encounter an object, then,
        although the fileserver is not working, we didn't clean up after it
        correctly.  In that case, we're in mid-creation already, so just
        delete the old, possibly-broken, object, and create a new one.
        """
        obj_name = f"{username}-fs"
        self._logger.debug("Creating job", name=obj_name, namespace=namespace)
        try:
            await self.batch_api.create_namespaced_job(namespace, job)
        except ApiException as e:
            if e.status == 409:
                # It already exists.  Delete and recreate it
                self._logger.warning(
                    "Job exists.  Deleting and recreating.",
                    name=obj_name,
                    namespace=namespace,
                )
                await self.delete_fileserver_job(username, namespace)
                await self._wait_for_fileserver_object_deletion(
                    obj_name=obj_name, namespace=namespace, kind="job"
                )
                await self.batch_api.create_namespaced_job(namespace, job)
                return
            raise KubernetesError.from_exception(
                "Error creating job",
                e,
                namespace=namespace,
                name=obj_name,
            ) from e

    async def delete_fileserver_job(
        self, username: str, namespace: str
    ) -> None:
        obj_name = f"{username}-fs"
        self._logger.debug("Deleting job", name=obj_name, namespace=namespace)
        try:
            await self.batch_api.delete_namespaced_job(
                obj_name, namespace, propagation_policy="Foreground"
            )
        except ApiException as e:
            if e.status == 404:
                return
            raise KubernetesError.from_exception(
                "Error deleting job",
                e,
                namespace=namespace,
                name=obj_name,
            ) from e

    async def create_fileserver_service(
        self, username: str, namespace: str, spec: V1Service
    ) -> None:
        """see create_fileserver_job() for the rationale behind retrying
        a conflict on creation."""
        obj_name = f"{username}-fs"
        try:
            await self.api.create_namespaced_service(namespace, spec)
        except ApiException as e:
            if e.status == 409:
                # It already exists.  Delete and recreate it
                self._logger.warning(
                    "Service exists.  Deleting and recreating.",
                    name=obj_name,
                    namespace=namespace,
                )
                await self.delete_fileserver_service(username, namespace)
                await self._wait_for_fileserver_object_deletion(
                    obj_name=obj_name, namespace=namespace, kind="service"
                )
                await self.api.create_namespaced_service(namespace, spec)
                return
            raise KubernetesError.from_exception(
                "Error creating service",
                e,
                namespace=namespace,
                name=obj_name,
            ) from e

    async def delete_fileserver_service(
        self, username: str, namespace: str
    ) -> None:
        obj_name = f"{username}-fs"
        try:
            await self.api.delete_namespaced_service(obj_name, namespace)
        except ApiException as e:
            if e.status == 404:
                return
            raise KubernetesError.from_exception(
                "Error deleting service",
                e,
                namespace=namespace,
                name=obj_name,
            ) from e

    async def create_fileserver_gafaelfawringress(
        self, username: str, namespace: str, spec: dict[str, Any]
    ) -> None:
        """see _create_fileserver_job() for the rationale behind retrying
        a conflict on creation."""
        obj_name = f"{username}-fs"
        crd_group = "gafaelfawr.lsst.io"
        crd_version = "v1alpha1"
        plural = "gafaelfawringresses"
        try:
            await self.custom_api.create_namespaced_custom_object(
                body=spec,
                group=crd_group,
                version=crd_version,
                namespace=namespace,
                plural=plural,
            )
        except ApiException as e:
            if e.status == 409:
                # It already exists.  Delete and recreate it
                self._logger.warning(
                    (
                        "Fileserver gafaelfawringress exists. "
                        + "Deleting and recreating."
                    ),
                    name=obj_name,
                    namespace=namespace,
                )
                await self.delete_fileserver_gafaelfawringress(
                    username, namespace
                )
                await self._wait_for_fileserver_object_deletion(
                    obj_name=obj_name,
                    namespace=namespace,
                    kind="gafaelfawringress",
                )
                await self.custom_api.create_namespaced_custom_object(
                    crd_group, crd_version, namespace, plural, spec
                )
            raise KubernetesError.from_exception(
                "Error creating gafaelfawringress",
                e,
                namespace=namespace,
                name=obj_name,
            ) from e

    async def delete_fileserver_gafaelfawringress(
        self, username: str, namespace: str
    ) -> None:
        obj_name = f"{username}-fs"
        crd_group = "gafaelfawr.lsst.io"
        crd_version = "v1alpha1"
        plural = "gafaelfawringresses"
        try:
            await self.custom_api.delete_namespaced_custom_object(
                crd_group, crd_version, namespace, plural, obj_name
            )
        except ApiException as e:
            if e.status == 404:
                return

            raise KubernetesError.from_exception(
                "Error deleting gafaelfawringress",
                e,
                namespace=namespace,
                name=obj_name,
            ) from e

    async def get_observed_fileserver_state(
        self, namespace: str
    ) -> dict[str, bool]:
        """Reconstruct the fileserver user map with what we can determine
        from the Kubernetes cluster.

        Objects with the name <username>-fs are presumed to be fileserver
        objects, where <username> can be assumed to be the name of the
        owning user.

        It returns a dict mapping strings to the value True, indicating those
        users who currently have fileservers.

        If the fileserver namespace does not exist, create it before moving
        ahead.
        """
        observed_state: dict[str, bool] = {}
        try:
            await self.api.read_namespace(namespace)
        except ApiException as e:
            if e.status == 404:
                self._logger.warning(f"No fileserver namespace '{namespace}'")
                return observed_state
            else:
                raise KubernetesError.from_exception(
                    "Error reading namespace",
                    e,
                    namespace=namespace,
                ) from e
        # Get all jobs
        all_jobs = await self.batch_api.list_namespaced_job(namespace)
        # Filter to those with the right label
        users = [
            x.metadata.labels.get("nublado.lsst.io/user")
            for x in all_jobs.items
            if x.metadata.labels.get("nublado.lsst.io/category", "")
            == "fileserver"
        ]
        # For each of these, check whether the fileserver is present
        for user in users:
            self._logger.debug(f"Checking user {user}")
            good = await self.check_fileserver_present(
                username=user, namespace=namespace
            )
            self._logger.debug(f"{user} fileserver good?  {good}")
            if good:
                observed_state[user] = True
        return observed_state

    async def check_fileserver_present(
        self, username: str, namespace: str
    ) -> bool:
        """Our determination of whether a user has a fileserver is this:

        We assume all fileserver objects other than the Pod are named
        <username>-fs, which we can do, since we created them and that's
        the convention we chose.  The pod will have a name
        "<username>-fs-<random-tag>", but more importantly it will have a
        label "job-name" equal to "<username>-fs".  We have a convenience
        method to retrieve the Pod active for a Job for a given username.

        A fileserver is working if:

        1) it has an Ingress which has an IP address.
        2) it has exactly one Pod in Running state due to a Job of the
           right name, and

        We do not check the GafaelfawrIngress, because the Custom API is
        clumsy, and the created Ingress is a requirement for whether the
        fileserver is running.  Although we create a Service, there's
        not much that can go wrong with it, so we opt to save the API
        call by assuming it's fine.

        We do it in this order because the operation that generally takes
        the longest is for the Ingress to get wired into the overall
        ingress-nginx structure.  In general, by the time the ingress is
        ready, everything else will be too.
        """
        obj_name = f"{username}-fs"
        try:
            self._logger.debug(f"Checking ingress for {username}")
            ing = await self.networking_api.read_namespaced_ingress(
                obj_name, namespace
            )
        except ApiException as e:
            self._logger.info(f"Ingress {obj_name} for {username} not found.")
            if e.status == 404:
                return False
            raise KubernetesError.from_exception(
                "Error reading ingress",
                e,
                namespace=namespace,
                name=obj_name,
            ) from e
        if (
            ing.status is None
            or ing.status.load_balancer is None
            or ing.status.load_balancer.ingress is None
        ):
            self._logger.info(
                f"Ingress {obj_name} for {username} does not "
                + "have status.load_balancer.ingress field."
            )
            return False
        if len(ing.status.load_balancer.ingress) < 1:
            self._logger.info(
                f"Ingress {obj_name} for {username} does not "
                + "have any ingress points."
            )
            return False
        ing_props = ing.status.load_balancer.ingress[0]
        if ing_props is None:
            self._logger.info(
                f"Ingress point for ingress {obj_name} for "
                + f"{username} does not have any properties."
            )
            return False
        if ing_props.ip is None or ing_props.ip == "":
            self._logger.info(
                f"Ingress {obj_name} for {username} does not "
                + "have an IP address."
            )
            return False
        # Ingress is OK.  Find the created job...
        self._logger.debug(f"Checking whether {username} has fileserver")
        try:
            self._logger.debug(f"Checking job for {username}")
            await self.batch_api.read_namespaced_job(obj_name, namespace)
        except ApiException as e:
            self._logger.info(f"Job {obj_name} for {username} not found.")
            if e.status == 404:
                self._logger.debug(f"Job {obj_name} for {username} not found.")
                return False
        # OK, we have a job.  Now let's see if the Pod from that job has
        # arrived...
        self._logger.debug(f"Checking Pod for {username}")
        pod = await self.get_fileserver_pod_for_user(username, namespace)
        if pod is None:
            self._logger.info(f"No Pod for {username}")
            return False
        if pod.status is None:
            self._logger.info(f"No Pod status for {pod.metadata.name}")
            return False
        if pod.status.phase != "Running":
            self._logger.info(
                f"Pod for {username} is in phase "
                + f"'{pod.status.phase}', not 'Running'."
            )
            return False
        return True

    async def wait_for_fileserver_object_deletion(
        self, username: str, namespace: str
    ) -> None:
        """This is a convenience wrapper that waits until all fileserver
        objects for a given user are deleted."""
        for kind in ("ingress", "gafaelfawringress", "service", "job"):
            await self._wait_for_fileserver_object_deletion(
                obj_name=f"{username}-fs", namespace=namespace, kind=kind
            )

    def _get_deletion_read_coro(
        self, obj_name: str, namespace: str, kind: str
    ) -> Coroutine[Any, Any, Any]:
        if kind == "job":
            return self.batch_api.read_namespaced_job(obj_name, namespace)
        elif kind == "gafaelfawringress":
            crd_group = "gafaelfawr.lsst.io"
            crd_version = "v1alpha1"
            plural = "gafaelfawringresses"
            # Note method name inconsistency
            return self.custom_api.get_namespaced_custom_object(
                crd_group, crd_version, namespace, plural, obj_name
            )
        elif kind == "service":
            return self.api.read_namespaced_service(obj_name, namespace)
        elif kind == "ingress":
            return self.networking_api.read_namespaced_ingress(
                obj_name, namespace
            )
        raise UnknownKindError(f"Don't know how to check for {kind} presence.")

    async def _wait_for_fileserver_object_deletion(
        self, obj_name: str, namespace: str, kind: str
    ) -> None:
        """This is as generic as I'm willing to go, and it's probably
        too generic already.

        FIXME: we should rely on event watches, rather than polling.
        """
        timeout = 30.0
        interval = 2.7
        self._logger.debug(
            f"Waiting for {kind} deletion",
            name=obj_name,
            namespace=namespace,
        )
        async with asyncio.timeout(timeout):
            while True:
                try:
                    await self._get_deletion_read_coro(
                        obj_name, namespace, kind
                    )
                except ApiException as e:
                    if e.status == 404:
                        return
                    raise KubernetesError.from_exception(
                        f"Error waiting for {kind} deletion",
                        e,
                        namespace=namespace,
                        name=obj_name,
                    ) from e
                self._logger.debug(
                    f"{kind} still present; waiting {interval}s "
                    + "then rechecking."
                )
                await asyncio.sleep(interval)

    async def get_fileserver_pod_for_user(
        self, username: str, namespace: str
    ) -> V1Pod | None:
        selector_string = f"job-name=={username}-fs"
        try:
            pods = await self.api.list_namespaced_pod(
                namespace=namespace, label_selector=selector_string
            )
            if not pods:
                return None
            if len(pods.items) > 1:
                raise KubernetesError(
                    f"Multiple pods match job {username}-fs",
                    namespace=namespace,
                )
            return pods.items[0]
        except ApiException as e:
            raise KubernetesError.from_exception(
                "Error listing pods",
                e,
                namespace=namespace,
            ) from e

    async def wait_for_fileserver_pod_up(
        self, pod_name: str, namespace: str
    ) -> None:
        await self._wait_for_fileserver_pod_up_down(
            pod_name, namespace, up=True
        )

    async def wait_for_fileserver_pod_down(
        self, pod_name: str, namespace: str
    ) -> None:
        await self._wait_for_fileserver_pod_up_down(
            pod_name, namespace, up=False
        )

    async def _wait_for_fileserver_pod_up_down(
        self, pod_name: str, namespace: str, up: bool
    ) -> None:
        """
        Waits for a fileserver pod to be up or down.

        Parameters
        ----------
        pod_name
            Name of the pod.
        namespace
            Namespace in which the pod is located.
        up
            If True, waits for pod to be in "Running" phase (for the
            duration of a single watch timeout).  If False, waits
            (indefinitely) for the pod to enter "Succeeded" or "Failed", or
            for the pod to go away.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        logger = self._logger.bind(name=pod_name, namespace=namespace)
        # Retrieve the object first. It's possible that it's already in the
        # correct phase, and we can return immediately. If not, we want to
        # start watching events with the next event after the current object
        # version.
        try:
            pod = await self.api.read_namespaced_pod(pod_name, namespace)
        except ApiException as e:
            if e.status == 404:
                if not up:
                    return
            raise KubernetesError.from_exception(
                "Error watching pod",
                e,
                namespace=namespace,
                name=pod_name,
            ) from e
        initial_phase = "Pending"
        if not up:
            initial_phase = "Running"
        if (
            pod is not None
            and pod.status is not None
            and pod.status.phase is not None
        ):
            if pod.status.phase != initial_phase:
                return pod.status.phase
        while True:
            logger.debug(
                f"Waiting for pod phase change from '{initial_phase}'"
            )
            try:
                phase = await self._pod_watch_loop(
                    pod_name, namespace, initial_phase=initial_phase
                )
                if phase is None:
                    logger.warning("New pod phase is None")
                else:
                    logger.debug(f"New pod phase is {phase.value}")
            except TimeoutError:
                if up:
                    raise
                logger.debug(
                    f"Pod watch timed out for {namespace}/{pod_name}"
                    + "; restarting."
                )
                continue
            if up:
                if phase is None or phase != KubernetesPodPhase.RUNNING:
                    msg = "Unexpected phase "
                    if phase is not None:
                        msg += f"'{phase.value}'"
                    else:
                        msg += "'None'"
                    msg += ".  Expected 'Running'."
                    raise KubernetesError(
                        message=msg,
                        name=pod_name,
                        namespace=namespace,
                    )
                logger.debug(f"Phase transition to {phase.value}")
                return
            # We're now in the waiting-for-down phase.
            if (
                phase is None
                or phase == KubernetesPodPhase.SUCCEEDED
                or phase == KubernetesPodPhase.FAILED
            ):
                # Pod finished no longer exists; that's what we were waiting
                # for.
                return
            if phase == KubernetesPodPhase.UNKNOWN:
                logger.warning(
                    f"Pod {namespace}/{pod_name} in 'Unknown' phase."
                )
            logger.debug(f"Phase is {phase.value}; looping.")
            # Loop and try again.

    async def _pod_watch_loop(
        self, pod_name: str, namespace: str, initial_phase: str
    ) -> KubernetesPodPhase | None:
        """Waits for a pod to change phase.  Returns the new phase.

        Parameters
        ----------
        pod_name
            Name of the pod.
        namespace
            Namespace in which the pod is located.
        initial_phase
            Phase we expect the pod to be in at the start of the watch.

        Returns
        -------
        KubernetesPodPhase
            New pod phase, or `None` if the pod has disappeared.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        TimeoutError
            Raised if watch expires.  The caller should decide on
            whether to restart the watch, or allow the error to propagate.
        """

        logger = self._logger.bind(name=pod_name, namespace=namespace)
        logger.debug(
            f"Waiting for pod phase change (inital = {initial_phase})"
        )
        # Retrieve the object first. It's possible that it's already in the
        # correct phase, and we can return immediately. If not, we want to
        # start watching events with the next event after the current object
        # version. Note that we treat Unknown the same as Pending; we rely on
        # the timeout and otherwise hope that Kubernetes will figure out the
        # phase.
        try:
            pod = await self.api.read_namespaced_pod(pod_name, namespace)
        except ApiException as e:
            if e.status == 404:
                return None
            raise KubernetesError.from_exception(
                "Error watching pod",
                e,
                namespace=namespace,
                name=pod_name,
            ) from e
        continuing_phases = ("Unknown", "Pending", "Running")
        if pod.status.phase not in continuing_phases:
            return KubernetesPodPhase(pod.status.phase)
        if pod.status.phase != initial_phase:
            return KubernetesPodPhase(pod.status.phase)
        # The pod is not in a terminal phase. Start the watch and
        # wait for it to change state.
        phase = await self._inner_watch_loop(
            method=self.api.list_namespaced_pod,
            watch_args={
                "namespace": namespace,
                "field_selector": f"metadata.name={pod_name}",
                "resource_version": pod.metadata.resource_version,
            },
            namespace=namespace,
            field=["status", "phase"],
            initial_value=initial_phase,
        )
        if phase is None:
            return None
        return KubernetesPodPhase(phase)

    async def _inner_watch_loop(
        self,
        *,
        method: Callable[[Any, Any], Any],
        watch_args: dict[str, Any],
        namespace: str,
        field: list[str],
        initial_value: Any,
        timeout: Optional[int] = None,
    ) -> Any:
        """Waits for a pod event that reports a value different from the
        intial value supplied.  Returns the new value.

        Parameters
        ----------
        method
            K8s API method (list_namespaced_<thing>) for watch.
        watch_args
            Arguments to supply to watch method, typically field or
            label selectors
        namespace
            Namespace in which the pod is located.
        field
            Components of path to field on object.  For instance, if you
            were waiting for a pod's phase to change, this would be
            [ "status", "phase" ].
        initial_value
            Value expected at start of watch; we only report changes from
            this value.
        timeout
            Watch timeout in seconds.

        Returns
        -------
        Primitive
            New value for pod field, or `None` if the pod has disappeared.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        TimeoutError
            Raised if watch expires.  The caller should decide on
            whether to restart the watch, or allow the error to propagate.

        Notes
        -----
        This is barely typed.  Don't call it directly; set up a wrapper method
        for the specific object types and fields you want to watch.
        """
        try:
            async for value in self._inner_watch_streaming_loop(
                method=method,
                watch_args=watch_args,
                namespace=namespace,
                field=field,
            ):
                if value != initial_value:
                    return value
        except KubernetesError as e:
            if e.status == "410":
                # Object resource version expired?
                # if we had one, try again without one.
                if watch_args.get("resource_version") is not None:
                    self._logger.warning(
                        "Resource version "
                        + f"{watch_args['resource_version']}"
                        + f" expired: {e}; retrying without "
                        + "resource version"
                    )
                    del watch_args["resource_version"]
                    return await self._inner_watch_loop(
                        method=method,
                        watch_args=watch_args,
                        namespace=namespace,
                        field=field,
                        initial_value=initial_value,
                        timeout=timeout,
                    )
                # If it wasn't a resource version timeout, or we already
                # were not setting watch_args, re-raise
                raise

        # If we fell through, the watch timed out.
        raise TimeoutError(f"Watch timed out after {timeout}s")

    async def _inner_watch_streaming_loop(
        self,
        *,
        method: Callable[[Any, Any], Any],
        watch_args: dict[str, Any],
        namespace: str,
        field: list[str],
        timeout: Optional[int] = None,
    ) -> AsyncIterator[Any]:
        """Yields the value in the specified field for the event's
        InvolvedObject when the event occurs.

        Parameters
        ----------
        method
            K8s API method (list_namespaced_<thing>) for watch.
        watch_args
            Arguments to supply to watch method, typically field or
            label selectors
        namespace
            Namespace in which the pod is located.
        field
            Components of path to field on object.  For instance, if you
            were waiting for a pod's phase to change, this would be
            [ "status", "phase" ].
        timeout
            Watch timeout in seconds.

        Returns
        -------
        Primitive
            New value for pod field, or `None` if the pod has disappeared.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        TimeoutError
            Raised if watch expires.  The caller should decide on
            whether to restart the watch, or allow the error to propagate.

        Notes
        -----
        This is barely typed.  Don't call it directly; set up a wrapper method
        for the specific object types and fields you want to watch.
        """
        # Set up timeout
        if timeout is None:
            timeout = int(self._spawn_timeout.total_seconds())
        if "timeout_seconds" not in watch_args:
            watch_args["timeout_seconds"] = timeout
        if "_request_timeout" not in watch_args:
            watch_args["_request_timeout"] = timeout
        w = watch.Watch()
        try:
            async with w.stream(method, **watch_args) as stream:
                async for event in stream:
                    ed = EventData.from_event(event)
                    # Rebind logger with object name
                    logger = self._logger.bind(
                        name=ed.name, namespace=namespace
                    )
                    logger.debug(
                        f"Event: {ed.type} ; kind {ed.kind} ; "
                        + f"object name: {ed.name}"
                    )
                    # Extract field from object; don't modify involved_object
                    value = deepcopy(ed.involved_object)
                    try:
                        for f in field:
                            value = value[f]
                    except (KeyError, TypeError):
                        message = (
                            f"Object '{ed.involved_object}' has no field "
                            + f"{'.'.join(field)}."
                        )
                        raise MissingObjectError(
                            message,
                            kind=ed.kind,
                            name=ed.name,
                            namespace=namespace,
                        )
                    yield value
        except ApiException as e:
            raise KubernetesError.from_exception(
                "Error watching object",
                e,
                namespace=namespace,
                name=ed.name,
            ) from e

        # If we fell through, the watch timed out.
        raise TimeoutError(f"Watch timed out after {timeout}s")
