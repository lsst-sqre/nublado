"""Tests for the prepuller service."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any
from unittest.mock import ANY

import pytest
from google.cloud.artifactregistry_v1 import DockerImage
from kubernetes_asyncio.client import (
    ApiException,
    V1ContainerImage,
    V1Node,
    V1NodeStatus,
    V1ObjectMeta,
    V1Pod,
)
from safir.testing.kubernetes import MockKubernetesApi, strip_none
from safir.testing.slack import MockSlackWebhook

from jupyterlabcontroller.config import Config
from jupyterlabcontroller.factory import Factory
from jupyterlabcontroller.models.domain.kubernetes import PodPhase
from jupyterlabcontroller.models.v1.prepuller_config import GARSourceConfig

from ..settings import TestObjectFactory
from ..support.config import configure
from ..support.data import (
    read_input_data,
    read_input_node_data,
    read_output_data,
)
from ..support.docker import MockDockerRegistry
from ..support.gar import MockArtifactRegistry


async def mark_pod_complete(
    mock_kubernetes: MockKubernetesApi, pod: V1Pod
) -> None:
    """Send a completion event for a pod and change its status to complete.

    Parameters
    ----------
    mock_kuberentes
        Mock Kubernetes API used by the tests.
    pod
        Pod whose status should be changed.
    """
    await mock_kubernetes.patch_namespaced_pod_status(
        pod.metadata.name,
        pod.metadata.namespace,
        [
            {
                "op": "replace",
                "path": "/status/phase",
                "value": PodPhase.SUCCEEDED.value,
            }
        ],
    )


@pytest.mark.asyncio
async def test_docker(
    factory: Factory,
    config: Config,
    mock_kubernetes: MockKubernetesApi,
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
    pod_list = await mock_kubernetes.list_namespaced_pod(namespace)
    with (std_result_dir / "prepull-objects.json").open("r") as f:
        expected = json.load(f)
    assert [strip_none(o.to_dict()) for o in pod_list.items] == expected

    # Update all of the pods to have a status of completed and send an event.
    for pod in pod_list.items:
        await mark_pod_complete(mock_kubernetes, pod)

    # The prepuller should notice the status change and delete the pods.
    await asyncio.sleep(0.2)
    pod_list = await mock_kubernetes.list_namespaced_pod(namespace)
    assert pod_list.items == []

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
    mock_gar: MockArtifactRegistry, mock_kubernetes: MockKubernetesApi
) -> None:
    """Test the prepuller service configured to talk to GAR."""
    config = configure("gar")
    assert isinstance(config.images.source, GARSourceConfig)
    known_images = read_input_data("gar", "known-images.json")
    for known_image in known_images:
        image = DockerImage(**known_image)
        parent, _, _ = image.name.split("@", 1)[0].rsplit("/", 2)
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
        assert images.model_dump(exclude_none=True) == expected

        menu_images = factory.image_service.menu_images()
        seen = {
            "menu": [asdict(e) for e in menu_images.menu],
            "dropdown": [asdict(e) for e in menu_images.dropdown],
        }
        expected = read_output_data("gar", "menu-before.json")
        assert seen == expected

        # There should be two running pods, one for each node. Since we didn't
        # configure any pod metadata, they should also not have owner
        # references.
        namespace = config.lab.namespace_prefix
        pod_list = await mock_kubernetes.list_namespaced_pod(namespace)
        tag = known_images[0]["tags"][0].replace("_", "-")
        assert [o.metadata.name for o in pod_list.items] == [
            f"prepull-{tag}-node1",
            f"prepull-{tag}-node2",
        ]
        assert all([not p.metadata.owner_references for p in pod_list.items])

        # Mark those nodes as complete, and two more should be started.
        for pod in pod_list.items:
            await mark_pod_complete(mock_kubernetes, pod)
        await asyncio.sleep(0.2)
        pod_list = await mock_kubernetes.list_namespaced_pod(namespace)
        tag = known_images[1]["tags"][0].replace("_", "-")
        assert sorted(o.metadata.name for o in pod_list.items) == [
            f"prepull-{tag}-node1",
            f"prepull-{tag}-node2",
        ]

        # Now, nothing more should be prepulled.
        for pod in pod_list.items:
            await mark_pod_complete(mock_kubernetes, pod)
        await asyncio.sleep(0.2)
        pod_list = await mock_kubernetes.list_namespaced_pod(namespace)
        assert pod_list.items == []

        images = factory.image_service.images()
        expected = read_output_data("gar", "images-after.json")
        assert images.model_dump(exclude_none=True) == expected

        menu_images = factory.image_service.menu_images()
        seen = {
            "menu": [asdict(e) for e in menu_images.menu],
            "dropdown": [asdict(e) for e in menu_images.dropdown],
        }
        expected = read_output_data("gar", "menu-after.json")
        assert seen == expected


@pytest.mark.asyncio
async def test_cycle(
    factory: Factory,
    mock_docker: MockDockerRegistry,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    config = configure("cycle")
    mock_docker.tags = read_input_data("cycle", "docker-tags.json")
    node_data = read_input_data("cycle", "nodes.json")
    nodes = []
    for name, data in node_data.items():
        node_images = [
            V1ContainerImage(names=d["names"], size_bytes=d["sizeBytes"])
            for d in data
        ]
        node = V1Node(
            metadata=V1ObjectMeta(name=name),
            status=V1NodeStatus(images=node_images),
        )
        nodes.append(node)
    mock_kubernetes.set_nodes_for_test(nodes)

    async with Factory.standalone(config) as factory:
        await factory.start_background_services()
        await asyncio.sleep(0.2)

        images = factory.image_service.images()
        expected = read_output_data("cycle", "images.json")
        assert images.model_dump(exclude_none=True) == expected

        menu_images = factory.image_service.menu_images()
        seen = {
            "menu": [asdict(e) for e in menu_images.menu],
            "dropdown": [asdict(e) for e in menu_images.dropdown],
        }
        expected = read_output_data("cycle", "menu.json")
        assert seen == expected


@pytest.mark.asyncio
async def test_gar_cycle(
    factory: Factory,
    mock_gar: MockArtifactRegistry,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    config = configure("gar-cycle")
    known_images = read_input_data("gar-cycle", "known-images.json")
    for known_image in known_images:
        image = DockerImage(**known_image)
        parent, _, _ = image.name.split("@", 1)[0].rsplit("/", 2)
        mock_gar.add_image_for_test(parent, image)
    nodes = read_input_node_data("gar-cycle", "nodes.json")
    mock_kubernetes.set_nodes_for_test(nodes)

    async with Factory.standalone(config) as factory:
        await factory.start_background_services()
        await asyncio.sleep(0.2)

        images = factory.image_service.images()
        expected = read_output_data("gar-cycle", "images.json")
        assert images.model_dump(exclude_none=True) == expected

        menu_images = factory.image_service.menu_images()
        seen = {
            "menu": [asdict(e) for e in menu_images.menu],
            "dropdown": [asdict(e) for e in menu_images.dropdown],
        }
        expected = read_output_data("gar-cycle", "menu.json")
        assert seen == expected


@pytest.mark.asyncio
async def test_kubernetes_error(
    factory: Factory,
    mock_kubernetes: MockKubernetesApi,
    mock_slack: MockSlackWebhook,
) -> None:
    def callback(method: str, *args: Any) -> None:
        if method == "create_namespaced_pod":
            raise ApiException(status=400, reason="Some error happened")

    mock_kubernetes.error_callback = callback

    await factory.start_background_services()
    await asyncio.sleep(0.2)

    obj = "userlabs/prepull-d-2077-10-23-node2"
    error = f"Error creating object (Pod {obj}, status 400)"
    assert mock_slack.messages == [
        {
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "text": f"Error in Nublado: {error}",
                        "type": "mrkdwn",
                        "verbatim": True,
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "text": "*Exception type*\nKubernetesError",
                            "type": "mrkdwn",
                            "verbatim": True,
                        },
                        {"text": ANY, "type": "mrkdwn", "verbatim": True},
                        {
                            "text": "*Status*\n400",
                            "type": "mrkdwn",
                            "verbatim": True,
                        },
                    ],
                },
                {
                    "type": "section",
                    "text": {
                        "text": f"*Object*\nPod {obj}",
                        "type": "mrkdwn",
                        "verbatim": True,
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "text": "*Error*\n```\nSome error happened\n```",
                        "type": "mrkdwn",
                        "verbatim": True,
                    },
                },
                {"type": "divider"},
            ]
        },
    ]


@pytest.mark.asyncio
async def test_conflict(
    factory: Factory,
    config: Config,
    mock_kubernetes: MockKubernetesApi,
    std_result_dir: Path,
) -> None:
    """Test handling of conflicts with a pre-existing prepuller pod."""
    namespace = config.lab.namespace_prefix
    with (std_result_dir / "prepull-conflict-objects.json").open("r") as f:
        expected = json.load(f)

    # Create a pod with the same name as the prepull pod that the prepuller
    # will want to create. Don't bother to try to make this a valid pod, just
    # make it something good enough to be accepted by the mock.
    pod = V1Pod(
        metadata=V1ObjectMeta(
            name=expected[0]["metadata"]["name"], namespace=namespace
        )
    )
    await mock_kubernetes.create_namespaced_pod(namespace, pod)

    # Now, start the prepuller and wait for it to kick off its first pods. It
    # should replace our dummy pod with the proper pod without complaining.
    await factory.start_background_services()
    await asyncio.sleep(0.2)
    pod_list = await mock_kubernetes.list_namespaced_pod(namespace)
    assert [strip_none(o.to_dict()) for o in pod_list.items] == expected
