"""Kubernetes storage layer for the Nublado lab controller."""

from __future__ import annotations

from base64 import b64encode
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any, Callable, Coroutine, Optional, Union

from kubernetes_asyncio import client, watch
from kubernetes_asyncio.client import (
    ApiClient,
    ApiException,
    V1ConfigMap,
    V1DeleteOptions,
    V1Ingress,
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
from ..exceptions import (
    DuplicateObjectError,
    KubernetesError,
    MissingObjectError,
)
from ..models.domain.kubernetes import (
    KubernetesEvent,
    KubernetesKindMethodContainer,
    KubernetesKindMethodMapper,
    KubernetesNodeImage,
    KubernetesPodEvent,
    KubernetesPodPhase,
    KubernetesPodWatchInfo,
    WatchEventType,
    get_watch_args,
)
from ..models.v1.lab import ResourceQuantity
from ..util import deslashify
from .kubernetes.creator import (
    ConfigMapStorage,
    NetworkPolicyStorage,
    PersistentVolumeClaimStorage,
    ResourceQuotaStorage,
    SecretStorage,
)
from .kubernetes.deleter import ServiceStorage
from .kubernetes.namespace import NamespaceStorage
from .kubernetes.watcher import KubernetesWatcher

__all__ = ["K8sStorageClient"]


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
    a method name.

    Now that I've said that, I'm going to build a map of kind-to-list-and-
    read-methods and still delegate most of the work to a hidden method
    that does the boilerplate.  But at least this way, you get reasonable
    debuggability.
    """

    def __init__(
        self,
        *,
        kubernetes_client: ApiClient,
        timeout: int,
        fileserver_creation_timeout: int,
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
        self._fileserver_creation_timeout = fileserver_creation_timeout
        self._logger = logger
        self._method_map = KubernetesKindMethodMapper()
        self._fill_method_map()

        self._config_map = ConfigMapStorage(self.k8s_api, logger)
        self._namespace = NamespaceStorage(self.k8s_api, logger)
        self._network_policy = NetworkPolicyStorage(self.k8s_api, logger)
        self._pvc = PersistentVolumeClaimStorage(self.k8s_api, logger)
        self._quota = ResourceQuotaStorage(self.k8s_api, logger)
        self._secret = SecretStorage(self.k8s_api, logger)
        self._service = ServiceStorage(self.k8s_api, logger)

    def _fill_method_map(self) -> None:
        """This sets up the object kinds that we have generic methods for,
        which are used by _get_object_maybe() and
        _wait_for_object_deletion().
        """
        self._method_map.add(
            "Ingress",
            KubernetesKindMethodContainer(
                object_type=V1Ingress,
                read_method=self.networking_api.read_namespaced_ingress,
                list_method=self.networking_api.list_namespaced_ingress,
            ),
        )
        self._method_map.add(
            "Job",
            KubernetesKindMethodContainer(
                object_type=V1Job,
                read_method=self.batch_api.read_namespaced_job,
                list_method=self.batch_api.list_namespaced_job,
            ),
        )
        self._method_map.add(
            "Pod",
            KubernetesKindMethodContainer(
                object_type=V1Pod,
                read_method=self.api.read_namespaced_pod,
                list_method=self.api.list_namespaced_pod,
            ),
        )
        self._supported_generic_kinds = self._method_map.list()

    #
    # Generic internal helper methods
    #

    async def _event_watch(
        self,
        method: Coroutine[Any, Any, Any],
        watch_args: dict[str, Any],
        transmogrifier: Optional[Callable[[dict[str, Any]], Any]] = None,
        retry_expired: bool = True,
        timeout: Optional[int] = None,
    ) -> AsyncIterator[Any]:
        if timeout is None:
            timeout = int(self._spawn_timeout.total_seconds())
        if "timeout_seconds" not in watch_args:
            watch_args["timeout_seconds"] = timeout
        if "_request_timeout" not in watch_args:
            watch_args["_request_timeout"] = timeout
        self._logger.debug(
            f"Starting watch with method {method}, "
            + f"watch args {watch_args}, "
            + f"and timeout {timeout}s."
        )
        w = watch.Watch()
        while True:
            try:
                async with w.stream(method, **watch_args) as stream:
                    async for raw_event in stream:
                        # Ideally we would use the parsed rather than
                        # the raw object and make use of the better
                        # Python models, but this doesn't seem to work
                        # with kubernetes_asyncio with our mock. This
                        # is probably a bug in the mock that we should
                        # fix, but use the raw object for now since
                        # it's not much harder.
                        if transmogrifier is None:
                            event = KubernetesEvent.from_event(raw_event)
                        else:
                            event = transmogrifier(raw_event)
                        self._logger.debug(f"Received event {event}")
                        yield event
                # If we got here, it was a timeout
                await w.close()
                raise TimeoutError(f"Event watch timed out after {timeout}s")
            except ApiException as e:
                if (
                    e.status == 410
                    and retry_expired
                    and "resource_version" in watch_args
                ):
                    self._logger.debug(
                        f"Resource version {watch_args['resource_version']} "
                        + "expired; retrying watch without it."
                    )
                    del watch_args["resource_version"]
                    continue
                await w.close()
                raise KubernetesError.from_exception(
                    f"Error in Kubernetes watch {method}->{watch_args}", e
                ) from e

    def _generic_kind_check(self, kind: str) -> None:
        if kind not in self._supported_generic_kinds:
            raise RuntimeError(
                f"Kind '{kind}' not in supported generic kinds "
                + f"{self._supported_generic_kinds}"
            )

    async def _get_object_maybe(
        self, kind: str, name: str, namespace: Optional[str]
    ) -> Union[V1Pod, V1Job, V1Ingress, V1Namespace] | None:
        """Try to read an object; if it's not there return None"""
        self._generic_kind_check(kind)
        if kind == "Namespace":
            namespace = None
        method = self._method_map.get(kind).read_method
        kwargs = {"name": name}
        if kind != "Namespace":
            if namespace is None:
                raise ValueError(f"Namespace cannot be None for kind {kind}")
            kwargs["namespace"] = namespace
        try:
            # FIXME figure out what we need to do to get typing correct
            obj = await method(**kwargs)  # type: ignore
            return obj
        except ApiException as e:
            if e.status == 404:
                return None
            raise KubernetesError.from_exception(
                "Error reading object",
                e,
                kind=kind,
                namespace=namespace,
                name=name,
            ) from e

    async def _wait_for_object_deletion(
        self, kind: str, name: str, namespace: Optional[str]
    ) -> None:
        """Here's the generic method we feared."""
        obj = await self._get_object_maybe(
            kind=kind, name=name, namespace=namespace
        )
        if obj is None:
            return
        if kind == "Namespace":
            namespace = None
        else:
            if namespace is None:
                raise ValueError(f"Namespace cannot be None for kind {kind}")
        watch_args = get_watch_args(obj.metadata)
        method = self._method_map.get(kind).list_method
        # Wait for an event saying the object is deleted.
        try:
            async for event in self._event_watch(
                method=method,
                watch_args=watch_args,
            ):
                if event.type == "DELETED":
                    return
            # I don't think we should get here
            raise RuntimeError(
                "Control reached end of _wait_for_object_deletion"
            )
        except TimeoutError:
            # Possible race condition, if object was deleted between the
            # _get_object_maybe() check and the watch.  Then there would not
            # have been any events to see.  So if we time out, then we should
            # check again whether the object really is gone after all.
            obj = await self._get_object_maybe(
                kind=kind, name=name, namespace=namespace
            )
            if obj is None:
                return
            raise

    async def _get_pod_watch_info(
        self, pod_name: str, namespace: str
    ) -> KubernetesPodWatchInfo | None:
        """Find a pod and then extract watch info from it.  If the pod doesn't
        exist, return None."""
        pod = await self.get_pod(pod_name, namespace)
        if pod is None:
            return None
        return KubernetesPodWatchInfo.from_pod(pod)

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

        phase = await self.get_pod_phase(name, namespace)
        if phase is None:
            error = "Pod disappeared while spawning"
            logger.error(error)
            phase = KubernetesPodPhase.FAILED

        # Log and return the results.
        if phase == KubernetesPodPhase.UNKNOWN:
            error = "Pod phase is Unknown, assuming it failed"
            logger.error(error)
        elif phase != KubernetesPodPhase.PENDING:
            logger.debug(f"Pod phase is now {phase}")
        return KubernetesPodEvent(message=message, phase=phase, error=error)

    #
    # Exported methods useful for multiple services
    #

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
        return await self._get_object_maybe(
            kind="Pod", name=name, namespace=namespace
        )

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
        pod = await self.get_pod(name, namespace)
        if pod is None:
            return None
        msg = f"Pod phase is {pod.status.phase}"
        self._logger.debug(msg, name=name, namespace=namespace)
        return pod.status.phase

    async def wait_for_pod_start(
        self, pod_name: str, namespace: str, timeout: timedelta | None = None
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
        timeout
            Timeout to wait for the pod to start.

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
        in_progress_phases = ("Unknown", "Pending")

        # Retrieve the object first. It's possible that it's already in the
        # correct phase, and we can return immediately. If not, we want to
        # start watching events with the next event after the current object
        # version. Note that we treat Unknown the same as Pending; we rely on
        # the timeout and otherwise hope that Kubernetes will figure out the
        # phase.
        pod = await self.get_pod(pod_name, namespace)
        if pod is None:
            return None
        if pod.status.phase not in in_progress_phases:
            return KubernetesPodPhase(pod.status.phase)

        # The pod is not in a terminal phase. Start the watch and wait for it
        # to change state.
        watcher = KubernetesWatcher(
            method=self.api.list_namespaced_pod,
            object_type=V1Pod,
            kind="Pod",
            name=pod.metadata.name,
            namespace=pod.metadata.namespace,
            resource_version=pod.metadata.resource_version,
            timeout=timeout or self._spawn_timeout,
            logger=self._logger,
        )
        try:
            async for event in watcher.watch():
                if event.action == WatchEventType.DELETED:
                    return None
                if event.object.status.phase not in in_progress_phases:
                    return KubernetesPodPhase(event.object.status.phase)
        finally:
            await watcher.close()

        # This should be impossible; someone called stop on the watcher.
        raise RuntimeError("Wait for pod start unexpectedly stopped")

    async def wait_for_pod_stop(
        self, pod_name: str, namespace: str
    ) -> KubernetesPodPhase | None:
        """Waits for a pod to terminate.

        Waits for the pod to reach a phase other than running or unknown, and
        returns the new phase. We treat unknown like running and assume
        eventually we will get back a real phase.

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
        logger.debug("Setting up watch to wait for pod stop")

        # Retrieve the object first. It's possible that it's already in the
        # correct phase, and we can return immediately. If not, we want to
        # start watching events with the next event after the current object
        # version. Note that we treat Unknown the same as Pending; we rely on
        # the timeout and otherwise hope that Kubernetes will figure out the
        # phase.
        watch_info = await self._get_pod_watch_info(pod_name, namespace)
        if watch_info is None:
            return None
        if watch_info.initial_phase not in ("Unknown", "Running"):
            return KubernetesPodPhase(watch_info.initial_phase)

        # The pod is not in a terminal phase. Start the watch and wait for it
        # to change state.

        def transmogrifier(
            event: dict[str, Any]
        ) -> Optional[KubernetesPodPhase]:
            if event["type"] == "DELETED":
                return None
            return KubernetesPodPhase(event["raw_object"]["status"]["phase"])

        while True:
            try:
                async for event in self._event_watch(
                    method=self.api.list_namespaced_pod,
                    watch_args=watch_info.watch_args,
                    transmogrifier=transmogrifier,
                ):
                    if event is None:
                        return None
                    if event not in (
                        KubernetesPodPhase.UNKNOWN,
                        KubernetesPodPhase.RUNNING,
                    ):
                        return event
            except TimeoutError:
                self._logger.debug(
                    "Watch timed out awaiting pod stop. " + "Restarting watch."
                )
                continue
        # We shouldn't get here
        raise RuntimeError("Control reached end of wait_for_pod_stop()")

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

        async for event in self._event_watch(
            method=method,
            watch_args=watch_args,
            transmogrifier=lambda x: str(x["raw_object"]["message"]),
            retry_expired=False,
        ):
            yield event

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
            argo_app = ""
        labels = {
            "nublado.lsst.io/category": category,
        }
        if argo_app:
            labels["argocd.argoproj.io/instance"] = argo_app
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

    #
    # Lab object methods
    #

    async def create_user_namespace(self, name: str) -> None:
        """Create the namespace for a user's lab.

        Parameters
        ----------
        name
            Name of the namespace.
        """
        body = V1Namespace(metadata=self.standard_metadata(name))
        await self._namespace.create(body, replace=True)

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
        await self._secret.create(namespace, secret)

    async def read_secret(self, name: str, namespace: str) -> V1Secret:
        secret = await self._secret.read(name, namespace)
        if not secret:
            msg = "Secret does not exist"
            self._logger.error(msg, name=name, namespace=namespace)
            raise MissingObjectError(
                message=f"Secret {namespace}/{name} does not exist",
                kind="Secret",
                name=name,
                namespace=namespace,
            )
        return secret

    async def create_pvcs(
        self, pvcs: list[V1PersistentVolumeClaim], namespace: str
    ) -> None:
        for pvc in pvcs:
            name = pvc.metadata.name
            pvc.metadata = self.standard_metadata(name, namespace)
            await self._pvc.create(namespace, pvc)

    async def create_configmap(
        self,
        name: str,
        namespace: str,
        data: dict[str, str],
        immutable: bool = True,
    ) -> None:
        configmap = V1ConfigMap(
            data={deslashify(k): v for k, v in data.items()},
            immutable=immutable,
            metadata=self.standard_metadata(name, namespace=namespace),
        )
        await self._config_map.create(namespace, configmap)

    async def create_network_policy(self, name: str, namespace: str) -> None:
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
        await self._network_policy.create(namespace, policy)

    async def create_lab_service(self, username: str, namespace: str) -> None:
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
        await self._service.create(namespace, service)

    async def create_quota(
        self, name: str, namespace: str, resource: ResourceQuantity
    ) -> None:
        quota = V1ResourceQuota(
            metadata=self.standard_metadata(name, namespace=namespace),
            spec=V1ResourceQuotaSpec(
                hard={
                    "limits.cpu": str(resource.cpu),
                    "limits.memory": str(resource.memory),
                }
            ),
        )
        await self._quota.create(namespace, quota)

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
                "Error creating object",
                e,
                kind="Pod",
                namespace=namespace,
                name=name,
            ) from e

    async def delete_namespace(self, name: str, wait: bool = False) -> None:
        """Delete a Kubernetes namespace.

        If the namespace doesn't exist, the deletion is silently successful.

        Parameters
        ----------
        name
            Name of the namespace.
        wait
            Whether to wait for the namespace to be deleted.
        """
        await self._namespace.delete(name, wait=wait)

    async def delete_pod(
        self,
        name: str,
        namespace: str,
        *,
        grace_period: timedelta | None = None,
    ) -> None:
        """Delete a pod.

        Parameters
        ----------
        name
            Name of the pod.
        namespace
            Namespace of the pod.
        grace_period
            How long to tell Kubernetes to wait between sending SIGTERM and
            sending SIGKILL to the pod process. The default if no grace period
            is set is 30s as of Kubernetes 1.27.1.

        Raises
        ------
        KubernetesError
            Raised if there is a Kubernetes API error.
        """
        try:
            if grace_period:
                grace = int(grace_period.total_seconds())

                # It's not clear whether the grace period has to be specified
                # in both the delete options body and as a query parameter,
                # but kubespawner sets both, so we'll do the same. I suspect
                # that only one or the other is needed.
                options = V1DeleteOptions(grace_period_seconds=grace)
                await self.api.delete_namespaced_pod(
                    name, namespace, body=options, grace_period_seconds=grace
                )
            else:
                await self.api.delete_namespaced_pod(name, namespace)
        except ApiException as e:
            if e.status == 404:
                return
            raise KubernetesError.from_exception(
                "Error deleting object",
                e,
                kind="Pod",
                namespace=namespace,
                name=name,
            ) from e

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
            ``ConfigMap`` object, or `None` if it does not exist.

        Raises
        ------
        KubernetesError
            Raised if a Kubernetes API call fails.
        """
        return await self._config_map.read(name, namespace)

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
        return await self._quota.read(name, namespace)

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
        return [
            n.metadata.name
            for n in await self._namespace.list()
            if n.metadata.name.startswith(f"{prefix}-")
        ]

    #
    # Prepuller methods
    #

    async def remove_completed_pod(self, podname: str, namespace: str) -> None:
        logger = self._logger.bind(name=podname, namespace=namespace)
        await self.wait_for_pod_start(podname, namespace)
        phase = await self.wait_for_pod_stop(podname, namespace)
        if phase is None:
            logger.warning("Pod was already missing")
            return
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
                kind="Pod",
                namespace=namespace,
                name=podname,
            ) from e
        return

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
            raise KubernetesError.from_exception(
                "Error reading node information", e, kind="Node"
            ) from e
        image_data = {}
        for node in nodes.items:
            name = node.metadata.name
            images = [
                KubernetesNodeImage.from_container_image(i)
                for i in node.status.images
                if node.status is not None and node.status.images is not None
            ]
            image_data[name] = images
        return image_data

    #
    # Methods for user fileservers
    #

    async def check_namespace(self, name: str) -> bool:
        """Check whether a namespace is present.

        Parameters
        ----------
        name
            Name of the namespace.

        Returns
        -------
        bool
            `True` if the namespace is present, `False` otherwise.
        """
        return await self._namespace.read(name) is not None

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
        name = f"{username}-fs"
        self._logger.debug("Creating job", name=name, namespace=namespace)
        try:
            await self.batch_api.create_namespaced_job(namespace, job)
        except ApiException as e:
            if e.status == 409:
                # It already exists.  Delete and recreate it
                self._logger.warning(
                    "Job exists.  Deleting and recreating.",
                    name=name,
                    namespace=namespace,
                )
                await self.delete_fileserver_job(username, namespace)
                await self._wait_for_object_deletion(
                    name=name, namespace=namespace, kind="Job"
                )
                await self.batch_api.create_namespaced_job(namespace, job)
                return
            raise KubernetesError.from_exception(
                "Error creating object",
                e,
                kind="Job",
                namespace=namespace,
                name=name,
            ) from e

    async def delete_fileserver_job(
        self, username: str, namespace: str
    ) -> None:
        name = f"{username}-fs"
        self._logger.debug("Deleting job", name=name, namespace=namespace)
        try:
            await self.batch_api.delete_namespaced_job(
                name, namespace, propagation_policy="Foreground"
            )
        except ApiException as e:
            if e.status == 404:
                return
            raise KubernetesError.from_exception(
                "Error deleting object",
                e,
                kind="Job",
                namespace=namespace,
                name=name,
            ) from e

    async def create_fileserver_service(
        self, namespace: str, spec: V1Service
    ) -> None:
        """see create_fileserver_job() for the rationale behind retrying
        a conflict on creation."""
        await self._service.create(namespace, spec, replace=True)

    async def delete_fileserver_service(
        self, username: str, namespace: str
    ) -> None:
        name = f"{username}-fs"
        await self._service.delete(name, namespace)

    async def create_fileserver_gafaelfawringress(
        self, username: str, namespace: str, spec: dict[str, Any]
    ) -> None:
        """see _create_fileserver_job() for the rationale behind retrying
        a conflict on creation."""
        name = f"{username}-fs"
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
                    name=name,
                    namespace=namespace,
                )
                await self.delete_fileserver_gafaelfawringress(
                    username, namespace
                )
                await self._wait_for_gafaelfawr_ingress_deletion(
                    name, namespace
                )
                await self.custom_api.create_namespaced_custom_object(
                    crd_group, crd_version, namespace, plural, spec
                )
            raise KubernetesError.from_exception(
                "Error creating object",
                e,
                kind="GafaelfawrIngress",
                namespace=namespace,
                name=name,
            ) from e

    async def _wait_for_gafaelfawr_ingress_deletion(
        self, name: str, namespace: str
    ) -> None:
        crd_group = "gafaelfawr.lsst.io"
        crd_version = "v1alpha1"
        plural = "gafaelfawringresses"
        try:
            gi = await self.custom_api.get_namespaced_custom_object(
                crd_group, crd_version, namespace, plural, name
            )
        except ApiException as e:
            if e.status == 404:
                return
            raise
        watch_args = get_watch_args(gi)
        watch_args["group"] = crd_group
        watch_args["version"] = crd_version
        watch_args["plural"] = plural
        async for event in self._event_watch(
            method=self.custom_api.list_namespaced_custom_object,
            watch_args=watch_args,
        ):
            if event.type == "DELETED":
                return
        # I don't think we should get here
        raise RuntimeError(
            "Control reached end of "
            + "_wait_for_gafaelfawr_ingress_deletion()"
        )

    async def delete_fileserver_gafaelfawringress(
        self, username: str, namespace: str
    ) -> None:
        name = f"{username}-fs"
        crd_group = "gafaelfawr.lsst.io"
        crd_version = "v1alpha1"
        plural = "gafaelfawringresses"
        try:
            await self.custom_api.delete_namespaced_custom_object(
                crd_group, crd_version, namespace, plural, name
            )
        except ApiException as e:
            if e.status == 404:
                return

            raise KubernetesError.from_exception(
                "Error deleting object",
                e,
                kind="GafaelfawrIngress",
                namespace=namespace,
                name=name,
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
        """
        observed_state: dict[str, bool] = {}
        if not await self.check_namespace(namespace):
            raise MissingObjectError(
                f"Missing user fileservers namespace {namespace}",
                kind="Namespace",
                name=namespace,
            )
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

        We assume all fileserver objects are named <username>-fs, which we
        can do, since we created them and that's the convention we chose.

        A fileserver is working if:

        1) it has exactly one Pod in Running state due to a Job of the
           right name, and
        2) it has an Ingress, which has status.load_balancer.ingress, and
           that inner ingress has an attribute "ip" which is not the
           empty string.

        We do not check the GafaelfawrIngress, because the Custom API is
        clumsy, and the created Ingress is a requirement for whether the
        fileserver is running.  Although we create a Service, there's
        not much that can go wrong with it, so we opt to save the API
        call by assuming it's fine.
        """
        name = f"{username}-fs"
        self._logger.debug(f"Checking whether {username} has fileserver")
        self._logger.debug(f"...checking Job for {username}")
        job = await self._get_object_maybe(
            kind="Job", name=name, namespace=namespace
        )
        if job is None:
            self._logger.debug(f"...Job {name} for {username} not found.")
            return False
        # OK, we have a job.  Now let's see if the Pod from that job has
        # arrived...
        self._logger.debug(f"...checking Pod for {username}")
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
        self._logger.debug(f"...checking Ingress for {username}")
        ingress = await self._get_object_maybe(
            kind="Ingress", name=name, namespace=namespace
        )
        if ingress is None:
            self._logger.info(f"...Ingress {name} for {username} not found.")
            return False
        if (
            ingress.status is None
            or ingress.status.load_balancer is None
            or ingress.status.load_balancer.ingress is None
            or len(ingress.status.load_balancer.ingress) < 1
            or ingress.status.load_balancer.ingress[0].ip == ""
        ):
            self._logger.info(
                f"...Ingress {name} for {username} does not have address."
            )
            return False
        self._logger.debug(f"...fileserver for {username} is OK.")
        return True

    async def wait_for_fileserver_object_deletion(
        self, username: str, namespace: str
    ) -> None:
        """Wait for the key fileserver objects (Ingress and Job) to
        be deleted.  We will presume that the GafaelfawrIngress deletion
        happens basically immediately after its corresponding Ingress
        is deleted.
        """
        name = "{username}-fs"
        for kind in ("Ingress", "Job"):
            await self._wait_for_object_deletion(
                kind=kind, name=name, namespace=namespace
            )

    async def get_fileserver_pod_for_user(
        self, username: str, namespace: str
    ) -> V1Pod | None:
        selector_string = f"job-name=={username}-fs"
        try:
            pods = await self.api.list_namespaced_pod(
                namespace=namespace, label_selector=selector_string
            )
            if not pods or not pods.items:
                return None
            if len(pods.items) > 1:
                raise DuplicateObjectError(
                    f"Multiple pods match job {username}-fs",
                    kind="Pod",
                    namespace=namespace,
                )
            return pods.items[0]
        except ApiException as e:
            raise KubernetesError.from_exception(
                "Error listing object",
                e,
                kind="Pod",
                namespace=namespace,
            ) from e

    async def wait_for_user_fileserver_ingress_ready(
        self, username: str, namespace: str, timeout: Optional[int] = None
    ) -> None:
        name = f"{username}-fs"
        ingress = await self._get_object_maybe(
            kind="Ingress", name=name, namespace=namespace
        )
        if ingress is None:
            # Well, OK, but we know what it's going to look like, so we
            # can do the watch anyway...
            expected_metadata = V1ObjectMeta(name=name, namespace=namespace)
            watch_args = get_watch_args(expected_metadata)
        else:
            watch_args = get_watch_args(ingress.metadata)
        # Do we already have a working ingress?
        if (
            ingress is not None
            and ingress.status is not None
            and ingress.status.load_balancer is not None
            and ingress.status.load_balancer.ingress is not None
            and len(ingress.status.load_balancer.ingress) > 0
            and ingress.status.load_balancer.ingress[0].ip != ""
        ):
            return

        def transmogrifier(event: dict[str, Any]) -> bool:
            """This is irritatingly complex, because of the whole object/
            raw_object thing.  Even though we *should* be, with the raw
            object, looking at the camelCase versions of the fields, when
            we patch the ingress in the test suite, what ends up getting
            set is the snake_case.  So we need to account for both.

            Eventually, we should fix the kubernetes mock to not need
            raw objects, and then this hack can go away.
            """
            obj = event["raw_object"]
            if "status" not in obj:
                return False
            lb: str = ""
            for item in ("load_balancer", "loadBalancer"):
                if item in obj["status"]:
                    lb = item
                    break
            if not lb:
                return False
            if "ingress" not in obj["status"][lb]:
                return False
            ing_list = obj["status"][lb]["ingress"]
            if ing_list is None or len(ing_list) < 1:
                return False
            ing = ing_list[0]
            if ing is None or "ip" not in ing or ing["ip"] == "":
                return False
            return True

        async for event in self._event_watch(
            method=self._method_map.get("Ingress").list_method,
            watch_args=watch_args,
            transmogrifier=transmogrifier,
            timeout=timeout,
        ):
            if event is True:
                return
        raise RuntimeError(
            "Control reached end of wait_for_user_fileserver_ingress_ready()"
        )
