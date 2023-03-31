"""Mock for the Kubernetes API.

This is a temporary derivative class and copy of a function from Safir to add
additional support required to test the lab controller. Once this is fleshed
out and confirmed working with lab controller tests, this functionality will
be rolled back into Safir.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections import defaultdict
from collections.abc import AsyncIterator, Iterator
from datetime import timedelta
from typing import Any, Optional
from unittest.mock import AsyncMock, Mock, patch

from kubernetes_asyncio import client, config
from kubernetes_asyncio.client import (
    ApiException,
    CoreV1Event,
    CoreV1EventList,
    V1ConfigMap,
    V1Namespace,
    V1NamespaceList,
    V1NetworkPolicy,
    V1Node,
    V1NodeList,
    V1ObjectMeta,
    V1ObjectReference,
    V1Pod,
    V1PodStatus,
    V1ResourceQuota,
    V1Secret,
    V1Service,
)
from safir.datetime import current_datetime
from safir.testing.kubernetes import MockKubernetesApi

__all__ = ["MockLabKubernetesApi", "patch_kubernetes"]


class MockLabKubernetesApi(MockKubernetesApi):
    """Mock Kubernetes API for testing.

    Attributes
    ----------
    initial_pod_status
        String value to set the status of pods to when created. If this is set
        to ``Running`` (the default), a pod start event will also be
        generated when the pod is created.
    """

    def __init__(self) -> None:
        super().__init__()
        self.initial_pod_status = "Running"
        self._nodes: list[V1Node] = []
        self._events: defaultdict[str, list[CoreV1Event]] = defaultdict(list)
        self._new_events: defaultdict[str, asyncio.Event]
        self._new_events = defaultdict(asyncio.Event)

    def add_event_for_test(self, namespace: str, event: CoreV1Event) -> None:
        """Add an event that will be returned by ``list_namespaced_event``."""
        event.metadata.resource_version = str(len(self._events[namespace]))
        self._events[namespace].append(event)
        self._new_events[namespace].set()

    def get_all_objects_in_namespace_for_test(
        self, namespace: str
    ) -> list[Any]:
        """Returns all objects in the given namespace.

        Note that due to how objects are stored in the mock, we can't
        distinguish between a missing namespace and a namespace with no
        objects. In both cases, the empty list is returned.

        Parameters
        ----------
        namespace
            Name of the namespace.

        Returns
        -------
        list of Any
            All objects found in that namespace, sorted by kind and then
            name.
        """
        if namespace not in self.objects:
            return []
        result = []
        for kind in sorted(self.objects[namespace].keys()):
            for _, body in sorted(self.objects[namespace][kind].items()):
                result.append(body)
        return result

    def set_nodes_for_test(self, nodes: list[V1Node]) -> None:
        """Set the node structures that will be returned by `list_node`.

        Parameters
        ----------
        nodes
            New node list to return.
        """
        self._nodes = V1NodeList(items=nodes)

    # CONFIGMAP API

    async def create_namespaced_config_map(
        self, namespace: str, body: V1ConfigMap
    ) -> None:
        if not body.metadata.namespace:
            body.metadata.namespace = namespace
        # Safir used the wrong parameter name, so this fixes that until Safir
        # can be fixed.
        await super().create_namespaced_config_map(namespace, body)

    # EVENTS API

    async def list_namespaced_event(
        self,
        namespace: str,
        *,
        field_selector: Optional[str] = None,
        resource_version: str = "0",
        timeout_seconds: Optional[int] = None,
        watch: bool = False,
        _preload_content: bool = True,
        _request_timeout: Optional[int] = None,
    ) -> CoreV1EventList:
        self._maybe_error("list_namespaced_event", namespace)
        if not watch:
            return CoreV1EventList(items=self._events[namespace])

        # All watches must not preload content since we're returning raw JSON.
        # This is done by the Kubernetes API Watch object.
        assert not _preload_content

        # When the timeout has expired.
        timeout = None
        if timeout_seconds is not None:
            timeout = current_datetime() + timedelta(seconds=timeout_seconds)

        # Returns all available events for this namespace, and then waits for
        # new events and returns them up to the timeout.
        async def next_event() -> AsyncIterator[bytes]:
            position = int(resource_version)
            while True:
                for event in self._events[namespace][position:]:
                    raw = {"type": "ADDED", "object": event.to_dict()}
                    yield json.dumps(raw).encode()
                    position += 1
                if timeout:
                    now = current_datetime()
                    timeout_left = (timeout - now).total_seconds()
                    if timeout_left < 0:
                        yield b""
                        return
                wait_event = self._new_events[namespace]
                try:
                    await asyncio.wait_for(wait_event.wait(), timeout_left)
                except TimeoutError:
                    yield b""
                    return

        event_generator = next_event()

        async def readline() -> bytes:
            return await event_generator.__anext__()

        # To support the watch interface, we have to simulate a streaming
        # aiohttp response. Thankfully, the watch only uses a minimal
        # interface, so we can get away with a simple mock.
        response = Mock()
        response.content.readline = AsyncMock()
        response.content.readline.side_effect = readline
        return response

    # NAMESPACE API

    async def create_namespace(self, body: V1Namespace) -> None:
        """Create a namespace.

        The mock doesn't truly track namespaces since it autocreates them when
        an object is created in that namespace (maybe that behavior should be
        optional). All this method therefore does is detect conflicts.

        Parameters
        ----------
        body
            Namespace to create.
        """
        self._maybe_error("create_namespace", body)
        if body.metadata.name in self.objects:
            msg = f"Namespace {body.metadata.name} already exists"
            raise ApiException(status=409, reason=msg)

    async def delete_namespace(self, name: str) -> None:
        self._maybe_error("delete_namespace")
        if name not in self.objects:
            raise ApiException(status=404, reason=f"{name} not found")
        del self.objects[name]

    async def read_namespace(self, name: str) -> V1Namespace:
        self._maybe_error("read_namespace", name)
        if name not in self.objects:
            msg = f"Namespace {name} not found"
            raise ApiException(status=404, reason=msg)
        return V1Namespace(metadata=V1ObjectMeta(name=name))

    async def list_namespace(self) -> V1NamespaceList:
        self._maybe_error("list_namespace")
        namespaces = []
        for namespace in self.objects:
            metadata = V1ObjectMeta(name=namespace)
            namespaces.append(V1Namespace(metadata=metadata))
        return V1NamespaceList(items=namespaces)

    # NETWORKPOLICY API

    async def create_namespaced_network_policy(
        self, namespace: str, body: V1NetworkPolicy
    ) -> None:
        self._maybe_error("create_namespaced_network_policy", namespace, body)
        name = body.metadata.name
        if not body.metadata.namespace:
            body.metadata.namespace = namespace
        else:
            assert namespace == body.metadata.namespace
        self._store_object(namespace, "NetworkPolicy", name, body)

    # NODE API

    async def list_node(self) -> list[V1Node]:
        self._maybe_error("list_node")
        return self._nodes

    # POD API

    async def create_namespaced_pod(self, namespace: str, body: V1Pod) -> None:
        """Add a pod to the mock Kubernetes.

        If ``initial_pod_status`` on the mock Kubernetes object is set to
        ``Running``, sets the state to ``Running`` and generates a startup
        event. Otherwise, the status is set to whatever ``initial_pod_status``
        is set to, and no even is generated.

        Parameters
        ----------
        namespace
            Namespace in which to create the pod.
        body
            Pod specification.
        """
        self._maybe_error("create_namespaced_pod", namespace, body)
        if not body.metadata.namespace:
            body.metadata.namespace = namespace
        else:
            assert namespace == body.metadata.namespace
        body.status = V1PodStatus(phase=self.initial_pod_status)
        self._store_object(namespace, "Pod", body.metadata.name, body)
        if self.initial_pod_status == "Running":
            event = CoreV1Event(
                metadata=V1ObjectMeta(
                    name=f"{body.metadata.name}-start", namespace=namespace
                ),
                message=f"Pod {body.metadata.name} started",
                involved_object=V1ObjectReference(
                    kind="Pod", name=body.metadata.name, namespace=namespace
                ),
            )
            self.add_event_for_test(namespace, event)

    async def read_namespaced_pod_status(
        self, name: str, namespace: str
    ) -> V1Pod:
        self._maybe_error("read_namespaced_pod_status", name, namespace)

        # Yes, this API actually returns a V1Pod. Presumably in the actual API
        # only the status portion is populated, but it shouldn't matter for
        # testing purposes.
        return self._get_object(namespace, "Pod", name)

    # RESOURCEQUOTA API

    async def create_namespaced_resource_quota(
        self, namespace: str, body: V1ResourceQuota
    ) -> None:
        self._maybe_error("create_namespaced_resource_quota", namespace, body)
        name = body.metadata.name
        if not body.metadata.namespace:
            body.metadata.namespace = namespace
        else:
            assert namespace == body.metadata.namespace
        self._store_object(namespace, "ResourceQuota", name, body)

    # SECRETS API

    async def create_namespaced_secret(
        self, namespace: str, body: V1Secret
    ) -> None:
        if not body.metadata.namespace:
            body.metadata.namespace = namespace
        # Safir used the wrong parameter name, so this fixes that until Safir
        # can be fixed.
        await super().create_namespaced_secret(namespace, body)

    # SERVICE API

    async def create_namespaced_service(
        self, namespace: str, body: V1Service
    ) -> None:
        self._maybe_error("create_namespaced_service", namespace, body)
        name = body.metadata.name
        if not body.metadata.namespace:
            body.metadata.namespace = namespace
        else:
            assert namespace == body.metadata.namespace
        self._store_object(namespace, "Service", name, body)


def patch_kubernetes() -> Iterator[MockLabKubernetesApi]:
    """Replace the Kubernetes API with a mock class.

    Copied from `safir.testing.kubernetes.patch_kubernetes` with no changes
    except the type of the mock class. This is temporary until this support
    has been merged back into Safir.

    Returns
    -------
    MockLabKubernetesApi
        The mock Kubernetes API object.
    """
    mock_api = MockLabKubernetesApi()
    with patch.object(config, "load_incluster_config"):
        patchers = []
        for api in ("CoreV1Api", "CustomObjectsApi", "NetworkingV1Api"):
            patcher = patch.object(client, api)
            mock_class = patcher.start()
            mock_class.return_value = mock_api
            patchers.append(patcher)
        mock_api_client = Mock(spec=client.ApiClient)
        mock_api_client.close = AsyncMock()
        with patch.object(client, "ApiClient") as mock_client:
            mock_client.return_value = mock_api_client
            os.environ["KUBERNETES_PORT"] = "tcp://10.0.0.1:443"
            yield mock_api
            del os.environ["KUBERNETES_PORT"]
        for patcher in patchers:
            patcher.stop()
