from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncGenerator
from typing import Dict, List

from kubernetes_asyncio import client, watch
from kubernetes_asyncio.client.api_client import ApiClient
from kubernetes_asyncio.client.models import (
    V1ConfigMap,
    V1LabelSelector,
    V1Namespace,
    V1NetworkPolicy,
    V1NetworkPolicyIngressRule,
    V1NetworkPolicyPort,
    V1NetworkPolicySpec,
    V1ObjectMeta,
    V1Pod,
    V1PodSpec,
    V1ResourceQuota,
    V1ResourceQuotaSpec,
    V1Secret,
    V1Service,
    V1ServicePort,
    V1ServiceSpec,
)
from kubernetes_asyncio.client.rest import ApiException
from structlog.stdlib import BoundLogger

from ..config import LabSecret
from ..exceptions import (
    KubernetesError,
    MissingSecretError,
    NSCreationError,
    WaitingForObjectError,
)
from ..models.domain.kubernetes import KubernetesNodeImage
from ..models.k8s import K8sPodPhase, Secret
from ..models.v1.lab import UserData, UserResourceQuantum
from ..util import deslashify


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

    def get_nonamespace_metadata(self, name: str) -> V1ObjectMeta:
        return V1ObjectMeta(
            name=name,
            labels={"argocd.argoproj.io/instance": "nublado-users"},
            annotations={
                "argocd.argoproj.io/compare-options": "IgnoreExtraneous",
                "argocd.argoproj.io/sync-options": "Prune=false",
            },
        )

    def get_std_metadata(self, name: str, namespace: str) -> V1ObjectMeta:
        return V1ObjectMeta(
            name=name,
            namespace=namespace,
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
                try:
                    await self.delete_namespace(namespace)
                except ApiException as e2:
                    if e2.status == 404:
                        return  # No such namespace is just fine (but weird).
                    estr = f"Failed to delete namespace {namespace}: {e2}"
                    self.logger.exception(estr)
                    raise NSCreationError(estr)
                # Wait until it's gone.
                await self.wait_for_namespace_deletion(namespace)
                # Just try again, and return *that* one's return value.
                return await self.create_user_namespace(namespace)
            # Outer try/except
            estr = f"Failed to create namespace {namespace}: {e}"
            self.logger.exception(estr)
            raise NSCreationError(estr)

    async def _k8s_create_namespace(self, ns_name: str) -> None:
        await self.api.create_namespace(
            V1Namespace(metadata=self.get_nonamespace_metadata(name=ns_name))
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
        return

    async def wait_for_namespace_deletion(
        self, namespace: str, interval: float = 0.2
    ) -> None:
        """Once it's underway, we loop, reading the
        namespace.  We eventually expect a 404, and when we get it we
        return.  If it doesn't arrive within the timeout, we raise the
        timeout exception, and if we get some other error, we repackage that
        and raise it.
        """
        elapsed = 0.0
        while elapsed < self.timeout:
            try:
                await self.api.read_namespace(namespace)
            except ApiException as e:
                if e.status == 404:
                    return
                raise WaitingForObjectError(str(e))
            await asyncio.sleep(interval)
            elapsed += interval
        raise WaitingForObjectError("Timed out waiting for ns deletion")

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
                    self.logger.warning(
                        f"Pod {namespace}/{podname} does not exist "
                        + f"at {elapsed}s."
                    )
                else:
                    self.logger.error(f"API Error: {e}")
                    raise WaitingForObjectError(str(e))
            phase = pod_status.phase
            if phase == K8sPodPhase.UNKNOWN:
                unk += 1
                if unk > unk_threshold:
                    raise WaitingForObjectError(
                        f"Pod {namespace}/{podname} stayed in unknown "
                        + f"longer than {unk_threshold * interval}s"
                    )
            if phase == K8sPodPhase.FAILED:
                raise WaitingForObjectError(
                    f"Pod {namespace}/{podname} failed: {pod_status.message}"
                )
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
                    self.logger.error(f"API Error: {e}")
                    raise WaitingForObjectError(str(e))
            phase = pod_status.phase
            if phase == K8sPodPhase.SUCCEEDED:
                try:
                    self.logger.info(
                        f"Removing Completed pod {namespace}/{podname}"
                    )
                    await self.api.delete_namespaced_pod(
                        name=podname, namespace=namespace
                    )
                    return
                except ApiException as e:
                    if e.status == 404:
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
            seen_messages: List[str] = []
            async for event in stream:
                # Check to see if pod has entered a state (i.e. not Pending or
                # Unknown) where we can stop watching.
                try:
                    pod = await self.api.read_namespaced_pod_status(
                        name=podname, namespace=namespace
                    )
                except ApiException as e:
                    # Dunno why it stopped, but we can stop watching
                    if e.status == 404:
                        phase = K8sPodPhase.FAILED  # A guess, but
                        # puts us into stopping state
                    else:
                        self.logger.error(f"API Error: {e}")
                        raise WaitingForObjectError(str(e))
                phase = pod.status.phase
                if phase in (
                    K8sPodPhase.RUNNING,
                    K8sPodPhase.SUCCEEDED,
                    K8sPodPhase.FAILED,
                ):
                    stopping = True
                if phase == K8sPodPhase.UNKNOWN:
                    self.logger.warning(
                        f"Pod {namespace}/{podname} in Unknown phase."
                    )
                # Now gather up our events and forward those
                message = event["raw_object"]["message"]
                if message and message not in seen_messages:
                    seen_messages.append(message)
                    self.logger.debug(f"Watch reporting '{message}'")
                    yield message
                if stopping:
                    break
            if stopping:
                w.stop()
                return

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
        base64_data["token"] = base64.b64encode(token.encode()).decode()
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
            metadata=self.get_std_metadata(name, namespace),
        )
        await self.api.create_namespaced_secret(
            namespace=namespace, body=secret
        )
        return

    async def read_secret(
        self,
        name: str,
        namespace: str,
    ) -> Secret:
        try:
            secret: V1Secret = await self.api.read_namespaced_secret(
                name, namespace
            )
        except Exception as exc:
            errstr = (
                f"Failed to read secret {name} in namespace {namespace}: "
                f"{exc}"
            )
            self.logger.error(errstr)
            raise MissingSecretError(errstr)
        secret_type = secret.type
        return Secret(data=secret.data, secret_type=secret_type)

    async def create_configmap(
        self,
        name: str,
        namespace: str,
        data: Dict[str, str],
        immutable: bool = True,
    ) -> None:
        mangled_data = dict()
        for k in data:
            mangled_data[deslashify(k)] = data[k]
        configmap = V1ConfigMap(
            data=mangled_data,
            immutable=immutable,
            metadata=self.get_std_metadata(name=name, namespace=namespace),
        )
        try:
            await self.api.create_namespaced_config_map(
                namespace=namespace, body=configmap
            )
        except Exception as exc:
            self.logger.error(f"Create config_map failed: {exc}")
            raise

    async def create_network_policy(
        self,
        name: str,
        namespace: str,
    ) -> None:
        api = client.NetworkingV1Api(self.k8s_api)
        # FIXME we need to further restrict Ingress to the right pods,
        # and Egress to ... external world, Hub, Portal, Gafaelfawr.  What
        # else?
        policy = V1NetworkPolicy(
            metadata=self.get_std_metadata(name, namespace=namespace),
            spec=V1NetworkPolicySpec(
                policy_types=["Ingress"],
                pod_selector=V1LabelSelector(
                    match_labels={"app": "jupyterhub", "component": "hub"}
                ),
                ingress=[
                    V1NetworkPolicyIngressRule(
                        ports=[
                            V1NetworkPolicyPort(
                                port=8888,
                            ),
                        ],
                    ),
                ],
            ),
        )
        try:
            await api.create_namespaced_network_policy(
                namespace=namespace, body=policy
            )
        except Exception as exc:
            self.logger.error(f"Network policy creation failed: {exc}")
            raise

    async def create_lab_service(self, username: str, namespace: str) -> None:
        svcname = "lab"
        svc = V1Service(
            metadata=self.get_std_metadata(svcname, namespace=namespace),
            spec=V1ServiceSpec(
                ports=[V1ServicePort(port=8888, target_port=8888)],
                selector={
                    "app": "lab",
                },
            ),
        )
        try:
            await self.api.create_namespaced_service(
                namespace=namespace, body=svc
            )
        except Exception as exc:
            self.logger.error(f"Service creation failed: {exc}")
            raise

    async def create_quota(
        self,
        name: str,
        namespace: str,
        quota: UserResourceQuantum,
    ) -> None:
        quota_obj = V1ResourceQuota(
            metadata=self.get_std_metadata(name, namespace=namespace),
            spec=V1ResourceQuotaSpec(
                hard={
                    "limits.cpu": str(quota.cpu),
                    "limits.memory": str(quota.memory),
                }
            ),
        )
        await self.api.create_namespaced_resource_quota(
            namespace=namespace, body=quota_obj
        )

    async def create_pod(
        self,
        name: str,
        namespace: str,
        pod: V1PodSpec,
        pull_secret: bool = False,
        labels: Dict[str, str] = dict(),
    ) -> None:
        if pull_secret:
            pod.image_pull_secrets = [{"name": "pull-secret"}]
        metadata = self.get_std_metadata(name, namespace=namespace)
        if labels:
            metadata.labels.update(labels)
        pod_obj = V1Pod(metadata=metadata, spec=pod)
        try:
            await self.api.create_namespaced_pod(
                namespace=namespace, body=pod_obj
            )
        except Exception as exc:
            self.logger.error(f"Error creating pod: {exc}")
            raise
        self.logger.debug(f"Created pod {namespace}/{name}")

    async def delete_namespace(
        self,
        namespace: str,
    ) -> None:
        """Delete the namespace with name ``namespace``.  If it doesn't exist,
        that's OK.
        """
        self.logger.debug(f"Deleting namespace {namespace}")
        try:
            await asyncio.wait_for(
                self.api.delete_namespace(namespace),
                self.timeout,
            )
        except ApiException as exc:
            if exc.status == 404:
                return  # "Not there to start with" is fine
            raise

    async def get_image_data(self) -> dict[str, list[KubernetesNodeImage]]:
        """Get the list of cached images from each node.

        Returns
        -------
        dict of str to list
            Map of nodes to lists of all cached images on that node.
        """
        nodes = await self.api.list_node()
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
    ) -> Dict[str, UserData]:
        observed_state = dict()
        api = self.api
        ns_prefix = f"{manager_namespace}-"
        namespaces = await api.list_namespace()
        namespace_list = [x.metadata.name for x in namespaces.items]
        user_namespaces = [
            x for x in namespace_list if x.startswith(ns_prefix)
        ]
        errorstr = ""
        for u_ns in user_namespaces:
            username = u_ns[len(ns_prefix) :]
            podname = f"nb-{username}"
            try:
                pod = await api.read_namespaced_pod_status(
                    name=podname, namespace=u_ns
                )
                observed_state[username] = UserData.from_pod(pod)
            except ApiException as e:
                if e.status == 404:
                    self.logger.warning(
                        f"Found user namespace for {username} but no pod; "
                        + "attempting namespace deletion."
                    )
                    try:
                        await self.delete_namespace(u_ns)
                        await self.wait_for_namespace_deletion(u_ns)
                    # Accumulate errors
                    except ApiException as e2:
                        if not errorstr:
                            errorstr = str(e2)
                        else:
                            errorstr += f", {e2}"
                else:
                    if not errorstr:
                        errorstr = str(e)
                    else:
                        errorstr += f", {e}"
        # If we have accumulated errors, re-raise
        if errorstr:
            raise KubernetesError(errorstr)
        return observed_state
