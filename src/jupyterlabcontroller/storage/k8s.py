"""Kubernetes storage layer for the Nublado lab controller."""

from __future__ import annotations

from base64 import b64encode
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

from kubernetes_asyncio import client
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
from ..exceptions import (
    DuplicateObjectError,
    KubernetesError,
    MissingObjectError,
)
from ..models.domain.kubernetes import (
    KubernetesNodeImage,
    PodPhase,
    PropagationPolicy,
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
from .kubernetes.custom import GafaelfawrIngressStorage
from .kubernetes.deleter import JobStorage, ServiceStorage
from .kubernetes.ingress import IngressStorage
from .kubernetes.namespace import NamespaceStorage
from .kubernetes.pod import PodStorage

__all__ = ["K8sStorageClient"]


class K8sStorageClient:
    def __init__(
        self,
        *,
        kubernetes_client: ApiClient,
        spawn_timeout: timedelta,
        logger: BoundLogger,
    ) -> None:
        self.k8s_api = kubernetes_client
        self.api = client.CoreV1Api(kubernetes_client)
        self._spawn_timeout = spawn_timeout
        self._logger = logger

        self._config_map = ConfigMapStorage(self.k8s_api, logger)
        self._gafaelfawr = GafaelfawrIngressStorage(self.k8s_api, logger)
        self._ingress = IngressStorage(self.k8s_api, logger)
        self._job = JobStorage(self.k8s_api, logger)
        self._namespace = NamespaceStorage(self.k8s_api, logger)
        self._network_policy = NetworkPolicyStorage(self.k8s_api, logger)
        self._pod = PodStorage(self.k8s_api, logger)
        self._pvc = PersistentVolumeClaimStorage(self.k8s_api, logger)
        self._quota = ResourceQuotaStorage(self.k8s_api, logger)
        self._secret = SecretStorage(self.k8s_api, logger)
        self._service = ServiceStorage(self.k8s_api, logger)

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
        return await self._pod.read(name, namespace)

    async def get_pod_phase(
        self, name: str, namespace: str
    ) -> PodPhase | None:
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
        PodPhase or None
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
    ) -> PodPhase | None:
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
        PodPhase
            New pod phase, or `None` if the pod has disappeared.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        return await self._pod.wait_for_phase(
            pod_name,
            namespace,
            until_not={PodPhase.UNKNOWN, PodPhase.PENDING},
            timeout=timeout or self._spawn_timeout,
        )

    async def wait_for_pod_stop(
        self, pod_name: str, namespace: str
    ) -> PodPhase | None:
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
        PodPhase
            New pod phase, or `None` if the pod has disappeared.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        """
        return await self._pod.wait_for_phase(
            pod_name,
            namespace,
            until_not={PodPhase.UNKNOWN, PodPhase.RUNNING},
            timeout=self._spawn_timeout,
        )

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
        async for message in self._pod.events_for_pod(pod_name, namespace):
            yield message

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
        labels: dict[str, str] | None = None,
        annotations: dict[str, str] | None = None,
        owner: V1OwnerReference | None = None,
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
        await self._pod.create(namespace, pod, replace=remove_on_conflict)

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
        await self._pod.delete(name, namespace, grace_period=grace_period)

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
        await self._pod.delete_after_completion(podname, namespace)

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

    async def create_fileserver_job(self, namespace: str, job: V1Job) -> None:
        """Create a ``Job`` for a file server.

        For all of our fileserver objects, if we are being asked to create
        them, it means we thought, based on our user map that we did not have
        a working file server. Any objects we encounter are therefore left
        over from a non-functional file server that wasn't cleaned up
        properly. In that case, delete the old object and then create a new
        one.
        """
        await self._job.create(
            namespace,
            job,
            replace=True,
            propagation_policy=PropagationPolicy.FOREGROUND,
        )

    async def delete_fileserver_job(
        self, username: str, namespace: str
    ) -> None:
        await self._job.delete(
            f"{username}-fs",
            namespace,
            propagation_policy=PropagationPolicy.FOREGROUND,
        )

    async def create_fileserver_service(
        self, namespace: str, spec: V1Service
    ) -> None:
        """Create the ``Service`` for a file server.

        See `create_fileserver_job` for the rationale behind retrying a
        conflict on creation.
        """
        await self._service.create(namespace, spec, replace=True)

    async def delete_fileserver_service(
        self, username: str, namespace: str
    ) -> None:
        name = f"{username}-fs"
        await self._service.delete(name, namespace)

    async def create_fileserver_gafaelfawringress(
        self, namespace: str, spec: dict[str, Any]
    ) -> None:
        """Create the ``GafaelfawrIngress`` for a file server.

        See `create_fileserver_job` for the rationale behind retrying a
        conflict on creation.
        """
        await self._gafaelfawr.create(namespace, spec, replace=True)

    async def delete_fileserver_gafaelfawringress(
        self, username: str, namespace: str
    ) -> None:
        name = f"{username}-fs"
        await self._gafaelfawr.delete(name, namespace)

    async def get_observed_fileserver_state(
        self, namespace: str
    ) -> dict[str, bool]:
        """Get file server state from Kubernetes.

        Reconstruct the fileserver user map with what we can determine
        from the Kubernetes cluster.

        Objects with the name :samp:`{username}-fs` are presumed to be file
        server objects, where *username* can be assumed to be the name of the
        owning user.

        Returns
        -------
        dict of bool
            Users who currently have fileservers.
        """
        observed_state: dict[str, bool] = {}
        if not await self.check_namespace(namespace):
            raise MissingObjectError(
                f"Missing user fileservers namespace {namespace}",
                kind="Namespace",
                name=namespace,
            )

        # Get all jobs with the right labels and extract the users.
        selector = "nublado.lsst.io/category=fileserver"
        users = [
            j.metadata.labels.get("nublado.lsst.io/user")
            for j in await self._job.list(namespace, label_selector=selector)
        ]

        # For each of these, check whether the fileserver is present
        for user in users:
            self._logger.debug(f"Checking user {user}")
            good = await self.check_fileserver_present(user, namespace)
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
        job = await self._job.read(name, namespace)
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
        ingress = await self._ingress.read(name, namespace)
        if not ingress:
            self._logger.info(f"...Ingress {name} for {username} not found.")
            return False
        if not self._ingress.has_ip_address(ingress):
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
        name = f"{username}-fs"
        self._logger.debug("Waiting for fileserver Ingress deletion")
        await self._ingress.wait_for_deletion(name, namespace)
        self._logger.debug("Waiting for fileserver Job deletion")
        await self._job.wait_for_deletion(name, namespace)

    async def get_fileserver_pod_for_user(
        self, username: str, namespace: str
    ) -> V1Pod | None:
        selector = f"job-name={username}-fs"
        pods = await self._pod.list(namespace, label_selector=selector)
        if not pods:
            return None
        if len(pods) > 1:
            msg = f"Multiple pods match job {username}-fs"
            raise DuplicateObjectError(msg, kind="Pod", namespace=namespace)
        return pods[0]

    async def wait_for_user_fileserver_ingress_ready(
        self, username: str, namespace: str, timeout: timedelta
    ) -> None:
        name = f"{username}-fs"
        await self._ingress.wait_for_ip_address(name, namespace, timeout)
