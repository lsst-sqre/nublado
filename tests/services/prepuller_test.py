"""Tests for the prepuller service."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from kubernetes_asyncio.client import (
    CoreV1Event,
    V1ObjectMeta,
    V1ObjectReference,
    V1Pod,
)

from jupyterlabcontroller.config import Config
from jupyterlabcontroller.factory import Factory
from jupyterlabcontroller.models.k8s import K8sPodPhase

from ..settings import TestObjectFactory
from ..support.kubernetes import MockLabKubernetesApi, strip_none


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
    await asyncio.sleep(0.1)

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
    await asyncio.sleep(0.1)

    # The default data configures Kubernetes with missing images on some
    # nodes. Check that we created the correct prepuller pods.
    namespace = config.lab.namespace_prefix
    objects = mock_kubernetes.get_all_objects_in_namespace_for_test(namespace)
    with (std_result_dir / "prepull-objects.json").open("r") as f:
        expected = json.load(f)
    assert [strip_none(o.to_dict()) for o in objects] == expected

    # Update all of the pods to have a status of completed and send an event.
    for pod in objects:
        assert isinstance(pod, V1Pod)
        name = pod.metadata.name
        event = CoreV1Event(
            metadata=V1ObjectMeta(name=f"{name}-done", namespace=namespace),
            message="Pod finished",
            involved_object=V1ObjectReference(
                kind="Pod", name=name, namespace=namespace
            ),
        )
        pod.status.phase = K8sPodPhase.SUCCEEDED.value
        mock_kubernetes.add_event_for_test(namespace, event)

    # The prepuller should notice the status change and delete the pods.
    await asyncio.sleep(0.1)
    objects = mock_kubernetes.get_all_objects_in_namespace_for_test(namespace)
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
