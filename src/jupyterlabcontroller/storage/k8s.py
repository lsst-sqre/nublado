"""Kubernetes storage layer for the Nublado lab controller."""

from __future__ import annotations

import asyncio
from base64 import b64encode
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any, Coroutine, Optional
from urllib.parse import urlparse

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
    V1PodTemplateSpec,
    V1ResourceQuota,
    V1ResourceQuotaSpec,
    V1Secret,
    V1Service,
    V1ServicePort,
    V1ServiceSpec,
)
from structlog.stdlib import BoundLogger

from ..config import LabSecret
from ..exceptions import KubernetesError, MissingObjectError
from ..models.domain.kubernetes import (
    KubernetesNodeImage,
    KubernetesPodEvent,
    KubernetesPodPhase,
)
from ..models.v1.lab import UserResourceQuantum
from ..util import deslashify

__all__ = ["K8sStorageClient"]

FILESERVER_LOCK = asyncio.Lock()


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
        self.batch_api = client.BatchV1Api(kubernetes_client)        
        self.custom_api = client.CustomObjectsApi(kubernetes_client)
        self.apps_api = client.AppsV1Api(kubernetes_client)
        self.networking_api = client.NetworkingV1Api(kubernetes_client)
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
        timeout = int(self._spawn_timeout.total_seconds())
        watch_args = {
            "namespace": namespace,
            "field_selector": f"involvedObject.name={pod_name}",
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

    def _standard_metadata(
        self, name: str, instance: str = "nublado-users"
    ) -> V1ObjectMeta:
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
            labels={"argocd.argoproj.io/instance": instance},
            annotations={
                "argocd.argoproj.io/compare-options": "IgnoreExtraneous",
                "argocd.argoproj.io/sync-options": "Prune=false",
            },
        )

    """It's really tempting to create generic methods for object
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

    # Methods for fileserver

    async def create_fileserver(
        self,
        username: str,
        namespace: str,
        job: V1Job,
        service: V1Service,
        gf_ingress: dict[str, Any],
    ) -> bool:
        with FILESERVER_LOCK:
            self._logger.info(f"Creating new fileserver for {username}...")
            self._logger.debug(f"...creating new job for {username}")
            await self._create_fileserver_job(username, namespace, job)
            self._logger.debug(f"...creating new service for {username}")
            await self._create_fileserver_service(
                username, namespace, spec=service
            )
            self._logger.debug(f"...creating new gfingress for {username}")
            await self._create_fileserver_gafaelfawringress(
                username, namespace, spec=gf_ingress
            )
            self._logger.debug(
                f"...polling until objects appear for {username}"
            )
            timeout = 60.0
            interval = 3.9
            try:
                async with asyncio.timeout(timeout):
                    while True:
                        good = await self.check_fileserver_present(
                            username, namespace
                        )
                        if good:
                            self._logger.info(
                                f"Fileserver created for {username}"
                            )
                            return True
                        await asyncio.sleep(interval)
            except asyncio.TimeoutError:
                self._logger.error(
                    f"Fileserver for {username} did not appear."
                )
                return False

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

    async def _create_fileserver_job(
        self, username: str, namespace: str, job: V1Job
    ) -> None:
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
                await self._delete_fileserver_job(username, namespace)
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

    async def _delete_fileserver_job(
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

    async def _create_fileserver_service(
        self, username: str, namespace: str, spec: V1Service
    ) -> None:
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
                await self._delete_fileserver_service(username, namespace)
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

    async def _delete_fileserver_service(
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

    async def _create_fileserver_gafaelfawringress(
        self, username: str, namespace: str, spec: dict[str, Any]
    ) -> None:
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
                await self._delete_fileserver_gafaelfawringress(
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
            x.metadata.labels.get("lsst.io/user")
            for x in all_jobs.items
            if x.metadata.labels.get("lsst.io/category", "") == "fileserver"
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

        We assume all fileserver objects are named <username>-fs, which we
        can do, since we created them and that's the convention we chose.

        A fileserver is working if:

        1) it has a Job with at least one active Pod
        2) it has a Service (properties not checked)
        3) it has an Ingress (properties not checked)

        We do not check the GafaelfawrIngress, because the Custom API is
        clumsy, and the created Ingress is a good proxy.

        If we find a broken fileserver, we delete all its objects.  In
        steady-state operations, this will happen when a fileserver Pod has
        seen no operations for its timeout period; the Pod will exit and
        the reconciliation task will note that the Job has no active Pods
        and take action to clean it up.
        """
        obj_name = f"{username}-fs"
        self._logger.debug(f"Checking whether {username} has fileserver")
        try:
            self._logger.debug(f"Checking job for {username}")
            job = await self.batch_api.read_namespaced_job(obj_name, namespace)
        except ApiException as e:
            self._logger.info(f"Job {obj_name} for {username} not found.")
            if e.status == 404:
                self._logger.debug(f"Job {obj_name} for {username} not found.")
                return False
            raise KubernetesError.from_exception(
                "Error reading job",
                e,
                namespace=namespace,
                name=obj_name,
            ) from e
        if job.status is None or job.status.active < 1:
            self._logger.info(
                f"Job {obj_name} has no active pods; "
                + f"terminating fileserver for {username}"
            )
            return False
        try:
            self._logger.debug(f"Checking service for {username}")
            job = await self.api.read_namespaced_service(obj_name, namespace)
        except ApiException as e:
            self._logger.info(f"Service {obj_name} for {username} not found.")
            if e.status == 404:
                return False
            raise KubernetesError.from_exception(
                "Error reading service",
                e,
                namespace=namespace,
                name=obj_name,
            ) from e
        try:
            self._logger.debug(f"Checking ingress for {username}")
            await self.networking_api.read_namespaced_ingress(
                obj_name, namespace
            )
        except ApiException as e:
            self._logger.info(f"Ingress {obj_name} for {username} not found.")
            if e.status == 404:
                return False
            raise KubernetesError.from_exception(
                "Error reading service",
                e,
                namespace=namespace,
                name=obj_name,
            ) from e
        return True

    async def remove_fileserver(self, username: str, namespace: str) -> None:
        """Remove the set of fileserver objects for a user.  It doesn't
        return until the objects are no longer present in Kubernetes.
        """
        with FILESERVER_LOCK:
            await self._delete_fileserver_job(username, namespace)
            await self._delete_fileserver_service(username, namespace)
            await self._delete_fileserver_gafaelfawringress(
                username, namespace
            )

            obj_name = f"{username}-fs"

            for kind in ("gafaelfawringress", "job", "service", "ingress"):
                await self._wait_for_fileserver_object_deletion(
                    obj_name=obj_name, namespace=namespace, kind=kind
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
        raise WaitingForObjectError(
            f"Don't know how to check for {kind} presence."
        )

    async def _wait_for_fileserver_object_deletion(
        self, obj_name: str, namespace: str, kind: str
    ) -> None:
        """This is as generic as I'm willing to go, and it's probably
        too generic already."""
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
