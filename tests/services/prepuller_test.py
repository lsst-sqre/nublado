"""Tests for the prepuller service."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from google.cloud.artifactregistry_v1 import DockerImage
from kubernetes_asyncio.client import (
    CoreV1Event,
    V1Node,
    V1NodeStatus,
    V1ObjectMeta,
    V1ObjectReference,
    V1Pod,
)

from jupyterlabcontroller.config import Config
from jupyterlabcontroller.factory import Factory
from jupyterlabcontroller.models.k8s import K8sPodPhase
from jupyterlabcontroller.models.v1.prepuller_config import GARSourceConfig

from ..settings import TestObjectFactory
from ..support.config import configure
from ..support.data import read_input_data, read_output_data
from ..support.gar import MockArtifactRegistry
from ..support.kubernetes import MockLabKubernetesApi, strip_none


def mark_pod_complete(
    mock_kubernetes: MockLabKubernetesApi, pod: V1Pod
) -> None:
    """Send a completion event for a pod and change its status to complete.

    Parameters
    ----------
    mock_kuberentes
        Mock Kubernetes API used by the tests.
    pod
        Pod whose status should be changed.
    """
    name = pod.metadata.name
    namespace = pod.metadata.namespace
    event = CoreV1Event(
        metadata=V1ObjectMeta(name=f"{name}-done", namespace=namespace),
        message="Pod finished",
        involved_object=V1ObjectReference(
            kind="Pod", name=name, namespace=namespace
        ),
    )
    pod.status.phase = K8sPodPhase.SUCCEEDED.value
    mock_kubernetes.add_event_for_test(namespace, event)


@pytest.mark.asyncio
async def test_docker(
    factory: Factory,
    config: Config,
    mock_kubernetes: MockLabKubernetesApi,
    obj_factory: TestObjectFactory,
    std_result_dir: Path,
) -> None:
    """Test the prepuller service configured to talk to Docker."""
    await factory.image_service.start()
    await asyncio.sleep(0.2)

    # With the default data, the image service running, and no prepuller, we
    # should see node1 as up-to-date but node2 out-of-date.
    status = factory.image_service.prepull_status()
    for image in status.images.pending:
        if image.tag == "d_2077_10_23":
            assert image.nodes == ["node1"]
            assert image.missing == ["node2"]
        elif image.tag == "w_2077_43":
            assert image.nodes == ["node1", "node2"]

    # Start the prepuller and give it a moment to run.
    await factory.prepuller.start()
    await asyncio.sleep(0.2)

    # The default data configures Kubernetes with missing images on some
    # nodes. Check that we created the correct prepuller pods.
    namespace = config.lab.namespace_prefix
    objects = mock_kubernetes.get_namespace_objects_for_test(namespace)
    with (std_result_dir / "prepull-objects.json").open("r") as f:
        expected = json.load(f)
    assert [strip_none(o.to_dict()) for o in objects] == expected

    # Update all of the pods to have a status of completed and send an event.
    for pod in objects:
        assert isinstance(pod, V1Pod)
        mark_pod_complete(mock_kubernetes, pod)

    # The prepuller should notice the status change and delete the pods.
    await asyncio.sleep(0.2)
    objects = mock_kubernetes.get_namespace_objects_for_test(namespace)
    assert objects == []

    # And now everything should show as up-to-date because we optimistically
    # update the image service even though it hasn't run again.
    status = factory.image_service.prepull_status()
    for image in status.images.pending:
        if image.tag == "d_2077_10_23":
            assert image.nodes == ["node1", "node2"]

    # Stop everything. (Ideally this should be done in a try/finally block.)
    await factory.image_service.stop()
    await factory.prepuller.stop()


@pytest.mark.asyncio
async def test_gar(
    mock_gar: MockArtifactRegistry, mock_kubernetes: MockLabKubernetesApi
) -> None:
    """Test the prepuller service configured to talk to GAR."""
    config = configure("gar")
    assert isinstance(config.images.source, GARSourceConfig)
    known_images = read_input_data("gar", "known-images.json")
    for known_image in known_images:
        image = DockerImage(**known_image)
        parent, _ = image.name.split("@", 1)
        mock_gar.add_image_for_test(parent, image)
    nodes = [
        V1Node(
            metadata=V1ObjectMeta(name="node1"),
            status=V1NodeStatus(images=[]),
        ),
        V1Node(
            metadata=V1ObjectMeta(name="node2"),
            status=V1NodeStatus(images=[]),
        ),
    ]
    mock_kubernetes.set_nodes_for_test(nodes)

    async with Factory.standalone(config) as factory:
        await factory.start_background_services()
        await asyncio.sleep(0.2)

        images = factory.image_service.images()
        expected = read_output_data("gar", "images-before.json")
        assert images.dict(exclude_none=True) == expected

        # There should be two running pods, one for each node.
        namespace = config.lab.namespace_prefix
        objects = mock_kubernetes.get_namespace_objects_for_test(namespace)
        tag = known_images[0]["tags"][0].replace("_", "-")
        assert [o.metadata.name for o in objects] == [
            f"prepull-{tag}-node1",
            f"prepull-{tag}-node2",
        ]

        # Mark those nodes as complete, and two more should be started.
        for pod in objects:
            assert isinstance(pod, V1Pod)
            mark_pod_complete(mock_kubernetes, pod)
        await asyncio.sleep(0.2)
        objects = mock_kubernetes.get_namespace_objects_for_test(namespace)
        tag = known_images[1]["tags"][0].replace("_", "-")
        assert [o.metadata.name for o in objects] == [
            f"prepull-{tag}-node1",
            f"prepull-{tag}-node2",
        ]

        # Now, nothing more should be prepulled.
        for pod in objects:
            assert isinstance(pod, V1Pod)
            mark_pod_complete(mock_kubernetes, pod)
        await asyncio.sleep(0.2)
        mock_kubernetes.get_namespace_objects_for_test(namespace) == []

        images = factory.image_service.images()
        expected = read_output_data("gar", "images-after.json")
        assert images.dict(exclude_none=True) == expected
