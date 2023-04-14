"""Kubernetes storage layer for the Nublado lab controller."""

from __future__ import annotations

import asyncio
from base64 import b64encode
from collections.abc import AsyncGenerator
from typing import Optional

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
from ..models.domain.kubernetes import KubernetesNodeImage
from ..models.k8s import K8sPodPhase, Secret
from ..models.v1.lab import UserData, UserResourceQuantum
from ..util import deslashify

__all__ = ["K8sStorageClient"]


class K8sStorageClient:
    def __init__(
        self, k8s_api: ApiClient, timeout: int, logger: BoundLogger
    ) -> None:
        self.k8s_api = k8s_api
        self.api = client.CoreV1Api(k8s_api)
        self.timeout = timeout
        self._logger = logger

    async def aclose(self) -> None:
        await self.k8s_api.close()

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
        while elapsed < self.timeout:
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

    async def wait_for_pod_creation(
        self, podname: str, namespace: str, interval: float = 0.2
    ) -> None:
        """This method polls to see whether the pod has been created
        successfully, and doesn't return until it has been.  If the pod
        failed, it raises an exception, if the pod stays in "Unknown" state
        for too long, it raises an exception, and if it doesn't go
        into "Running" or "Completed" state in 570 seconds, it raises an
        exception.
        """
        logger = self._logger.bind(name=podname, namespace=namespace)
        logger.debug("Waiting for pod creation")
        elapsed = 0.0
        unk = 0
        unk_threshold = 20
        pod_timeout = 570  # 9-1/2 minutes.  Arbitrary.
        while elapsed < pod_timeout:
            try:
                pod = await self.api.read_namespaced_pod_status(
                    name=podname, namespace=namespace
                )  # Actually returns a V1Pod, not a V1PodStatus
                pod_status = pod.status
            except ApiException as e:
                if e.status == 404:
                    logger.warning(f"Pod does not exist ({elapsed}s elapsed)")
                else:
                    raise KubernetesError.from_exception(
                        "Error reading pod status",
                        e,
                        namespace=namespace,
                        name=podname,
                    ) from e
            else:
                phase = pod_status.phase
                if phase == K8sPodPhase.UNKNOWN:
                    unk += 1
                    if unk > unk_threshold:
                        raise WaitingForObjectError(
                            f"Pod {namespace}/{podname} stayed in unknown "
                            + f"longer than {unk_threshold * interval}s"
                        )
                if phase == K8sPodPhase.FAILED:
                    msg = (
                        f"Pod {namespace}/{podname} failed:"
                        f" {pod_status.message}"
                    )
                    raise WaitingForObjectError(msg)
                if phase in (K8sPodPhase.RUNNING, K8sPodPhase.SUCCEEDED):
                    # "Succeeded" would be weird for a Lab pod.
                    return
            # If we got this far, it's "Pending" and we just wait a bit
            # and look again.
            unk = 0
            await asyncio.sleep(interval)
            elapsed += interval
        # And if we get this far, it timed out without being created.
        raise WaitingForObjectError(
            f"Timed out waiting for pod {namespace}/{podname} creation"
        )

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
            if phase == K8sPodPhase.SUCCEEDED:
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

    async def reflect_pod_events(
        self, namespace: str, podname: str
    ) -> AsyncGenerator:
        """This can probably be rolled into the wait_for_pod above
        somehow, but I'm implementing this separately because I haven't
        quite seen the right shape of it yet.

        This is going to yield messages that are reflected from K8s while the
        pod is Pending, and return once pod is Running, Completed, or Failed.
        """
        logger = self._logger.bind(namespace=namespace, pod=podname)
        logger.debug("Watching for pod events")
        w = watch.Watch()
        method = self.api.list_namespaced_event
        watch_args = {
            "namespace": namespace,
            "field_selector": f"involvedObject.name={podname}",
            "timeout_seconds": 30,
            "_request_timeout": 30,
        }
        stopping = False
        async with w.stream(method, **watch_args) as stream:
            seen_messages = []
            async for event in stream:
                raw_event = event["raw_object"]
                logger.debug(
                    "Saw Kubernetes event",
                    object=raw_event.get("involved_object"),
                    message=raw_event.get("message"),
                )
                # Check to see if pod has entered a state (i.e. not Pending or
                # Unknown) where we can stop watching.
                try:
                    pod = await self.api.read_namespaced_pod_status(
                        name=podname, namespace=namespace
                    )
                except ApiException as e:
                    # Dunno why it stopped, but we can stop watching
                    if e.status == 404:
                        logger.error("Pod disappeared while spawning")
                        phase = K8sPodPhase.FAILED  # A guess, but
                        # puts us into stopping state
                    else:
                        raise KubernetesError.from_exception(
                            "Error reading pod status",
                            e,
                            namespace=namespace,
                            name=podname,
                        ) from e
                phase = pod.status.phase
                logger.debug(f"Pod phase is now {phase}")
                if phase in (
                    K8sPodPhase.RUNNING,
                    K8sPodPhase.SUCCEEDED,
                    K8sPodPhase.FAILED,
                ):
                    stopping = True
                if phase == K8sPodPhase.UNKNOWN:
                    logger.warning("Pod phase is Unknown")

                # Now gather up our events and forward those
                message = raw_event.get("message")
                if message and message not in seen_messages:
                    seen_messages.append(message)
                    logger.debug("Pod watch reported message", message=message)
                    yield message
                if stopping:
                    break
            if stopping:
                w.stop()
                return

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
        owner: Optional[V1OwnerReference] = None,
    ) -> None:
        self._logger.debug("Creating pod", name=name, namespace=namespace)
        metadata = self._standard_metadata(name)
        if labels:
            metadata.labels.update(labels)
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
                self.api.delete_namespace(name), self.timeout
            )
        except ApiException as e:
            if e.status == 404:
                return
            msg = "Error deleting namespace"
            raise KubernetesError.from_exception(msg, e, name=name) from e
        except TimeoutError:
            msg = (
                f"Timed out after {self.timeout}s waiting for namespace"
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

    async def get_observed_user_state(
        self, manager_namespace: str
    ) -> dict[str, UserData]:
        observed_state = {}
        api = self.api
        ns_prefix = f"{manager_namespace}-"
        namespaces = await api.list_namespace()
        namespace_list = [x.metadata.name for x in namespaces.items]
        user_namespaces = [
            x for x in namespace_list if x.startswith(ns_prefix)
        ]
        for u_ns in user_namespaces:
            username = u_ns[len(ns_prefix) :]
            podname = f"nb-{username}"
            self._logger.debug(
                "Reading existing user pod", name=podname, namespace=u_ns
            )
            try:
                pod = await api.read_namespaced_pod(
                    name=podname, namespace=u_ns
                )
                observed_state[username] = UserData.from_pod(pod)
            except ApiException as e:
                if e.status == 404:
                    self._logger.warning(
                        f"Found user namespace for {username} but no pod; "
                        + "attempting namespace deletion"
                    )
                    await self.delete_namespace(u_ns)
                    await self.wait_for_namespace_deletion(u_ns)
                raise KubernetesError.from_exception(
                    "Error reading pod", e, namespace=u_ns, name=podname
                ) from e
        return observed_state

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
