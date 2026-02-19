"""Tests for the prepuller service."""

import asyncio
from dataclasses import asdict
from typing import Any
from unittest.mock import ANY

import pytest
from google.cloud.artifactregistry_v1 import DockerImage
from kubernetes_asyncio.client import (
    ApiException,
    V1Node,
    V1NodeStatus,
    V1ObjectMeta,
    V1Pod,
)
from safir.testing.kubernetes import MockKubernetesApi
from safir.testing.slack import MockSlackWebhook

from nublado.controller.config import Config
from nublado.controller.factory import Factory
from nublado.controller.models.domain.kubernetes import PodPhase
from nublado.controller.models.v1.prepuller import GARSourceOptions

from ...support.config import configure
from ...support.data import NubladoData
from ...support.docker import MockDockerRegistry
from ...support.gar import MockArtifactRegistry


async def assert_objects_match(
    data: NubladoData, key: str, mock_kubernetes: MockKubernetesApi
) -> None:
    """Assert the created prepull objects match the expected set.

    Parameters
    ----------
    data
        Test data.
    key
        Name of the data file defining the expected output.
    mock_kubernetes
        Kubernetes mock used to retrieve the created objects.
    """
    pods = await mock_kubernetes.list_namespaced_pod("nublado")
    data.assert_kubernetes_matches(pods.items, f"controller/objects/{key}")


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
    data: NubladoData,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    """Test the prepuller service configured to talk to Docker."""
    await factory.image_service.refresh()

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
    await factory.start_background_services()
    await asyncio.sleep(0.2)

    # The default data configures Kubernetes with missing images on some
    # nodes. Check that we created the correct prepuller pods.
    await assert_objects_match(data, "prepull", mock_kubernetes)

    # Update all of the pods to have a status of completed and send an event.
    pod_list = await mock_kubernetes.list_namespaced_pod("nublado")
    for pod in pod_list.items:
        await mark_pod_complete(mock_kubernetes, pod)

    # The prepuller should notice the status change and delete the pods.
    await asyncio.sleep(0.2)
    pod_list = await mock_kubernetes.list_namespaced_pod("nublado")
    assert pod_list.items == []

    # And now everything should show as up-to-date because we optimistically
    # update the image service even though it hasn't run again.
    status = factory.image_service.prepull_status()
    for image in status.images.pending:
        if image.tag == "d_2077_10_23":
            assert image.nodes == ["node1", "node2"]


@pytest.mark.asyncio
async def test_gar(
    data: NubladoData,
    mock_gar: MockArtifactRegistry,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    """Test the prepuller service configured to talk to GAR."""
    config = await configure(data, "gar")
    assert isinstance(config.images.source, GARSourceOptions)
    known_images = data.read_json("controller/tags/gar")
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
        async with asyncio.timeout(1):
            await factory.start_background_services()
        await asyncio.sleep(0.2)

        images = factory.image_service.images()
        data.assert_pydantic_matches(images, "controller/images/gar-before")

        menu_images = factory.image_service.menu_images()
        seen = {
            "menu": [asdict(e) for e in menu_images.menu],
            "dropdown": [asdict(e) for e in menu_images.dropdown],
        }
        data.assert_json_matches(seen, "controller/menu/gar-before")

        # There should be two running pods, one for each node.
        pod_list = await mock_kubernetes.list_namespaced_pod("nublado")
        tag = known_images[1]["tags"][0].replace("_", "-")
        assert [o.metadata.name for o in pod_list.items] == [
            f"prepull-{tag}-node1",
            f"prepull-{tag}-node2",
        ]

        # Mark those nodes as complete, and two more should be started.
        for pod in pod_list.items:
            await mark_pod_complete(mock_kubernetes, pod)
        await asyncio.sleep(0.2)
        pod_list = await mock_kubernetes.list_namespaced_pod("nublado")
        tag = known_images[2]["tags"][0].replace("_", "-")
        assert sorted(o.metadata.name for o in pod_list.items) == [
            f"prepull-{tag}-node1",
            f"prepull-{tag}-node2",
        ]

        # Now, nothing more should be prepulled.
        for pod in pod_list.items:
            await mark_pod_complete(mock_kubernetes, pod)
        await asyncio.sleep(0.2)
        pod_list = await mock_kubernetes.list_namespaced_pod("nublado")
        assert pod_list.items == []

        images = factory.image_service.images()
        data.assert_pydantic_matches(images, "controller/images/gar-after")

        menu_images = factory.image_service.menu_images()
        seen = {
            "menu": [asdict(e) for e in menu_images.menu],
            "dropdown": [asdict(e) for e in menu_images.dropdown],
        }
        data.assert_json_matches(seen, "controller/menu/gar-after")


@pytest.mark.asyncio
async def test_cycle(
    data: NubladoData,
    mock_docker: MockDockerRegistry,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    config = await configure(data, "cycle")
    mock_docker.tags = data.read_json("controller/tags/docker-cycle")
    nodes = data.read_nodes("controller/nodes/cycle")
    mock_kubernetes.set_nodes_for_test(nodes)

    async with Factory.standalone(config) as factory:
        await factory.start_background_services()
        await asyncio.sleep(0.2)

        images = factory.image_service.images()
        data.assert_pydantic_matches(images, "controller/images/cycle")

        menu_images = factory.image_service.menu_images()
        seen = {
            "menu": [asdict(e) for e in menu_images.menu],
            "dropdown": [asdict(e) for e in menu_images.dropdown],
        }
        data.assert_json_matches(seen, "controller/menu/cycle")


@pytest.mark.asyncio
async def test_gar_cycle(
    data: NubladoData,
    mock_gar: MockArtifactRegistry,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    config = await configure(data, "gar-cycle")
    known_images = data.read_json("controller/tags/gar-cycle")
    for known_image in known_images:
        image = DockerImage(**known_image)
        parent, _, _ = image.name.split("@", 1)[0].rsplit("/", 2)
        mock_gar.add_image_for_test(parent, image)
    nodes = data.read_nodes("controller/nodes/gar-cycle")
    mock_kubernetes.set_nodes_for_test(nodes)

    async with Factory.standalone(config) as factory:
        await factory.start_background_services()
        await asyncio.sleep(0.2)

        images = factory.image_service.images()
        data.assert_pydantic_matches(images, "controller/images/gar-cycle")

        menu_images = factory.image_service.menu_images()
        seen = {
            "menu": [asdict(e) for e in menu_images.menu],
            "dropdown": [asdict(e) for e in menu_images.dropdown],
        }
        data.assert_json_matches(seen, "controller/menu/gar-cycle")


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

    await factory.image_service.refresh()
    await factory.prepuller.prepull_images()
    obj = "nublado/prepull-d-2077-10-23-node2"
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
    *,
    factory: Factory,
    config: Config,
    data: NubladoData,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    """Test handling of conflicts with a pre-existing prepuller pod."""
    expected = data.read_json("controller/objects/prepull-conflict")

    # Create a pod with the same name as the prepull pod that the prepuller
    # will want to create. Don't bother to try to make this a valid pod, just
    # make it something good enough to be accepted by the mock.
    pod = V1Pod(metadata=V1ObjectMeta(name=expected[0]["metadata"]["name"]))
    await mock_kubernetes.create_namespaced_pod("nublado", pod)

    # Now, start the prepuller and wait for it to kick off its first pods. It
    # should replace our dummy pod with the proper pod without complaining.
    await factory.start_background_services()
    await asyncio.sleep(0.2)
    await assert_objects_match(data, "prepull-conflict", mock_kubernetes)


@pytest.mark.asyncio
async def test_node_change(
    *,
    factory: Factory,
    config: Config,
    data: NubladoData,
    mock_kubernetes: MockKubernetesApi,
    mock_slack: MockSlackWebhook,
) -> None:
    """Test what happens when a node is removed in the middle of prepulling.

    Previous versions of the Nublado controller threw uncaught exceptions due
    to consistency issues in internal data structures.
    """
    await factory.image_service.refresh()

    # Start the prepuller and give it a moment to run.
    await factory.start_background_services()
    await asyncio.sleep(0.2)

    # The default data configures Kubernetes with missing images on some
    # nodes. Check that we created the correct prepuller pods.
    await assert_objects_match(data, "prepull", mock_kubernetes)

    # Remove the last node from the list of nodes and refresh the image
    # service, simulating a node removal in the middle of a run.
    nodes = await mock_kubernetes.list_node()
    mock_kubernetes.set_nodes_for_test(nodes.items[:-1])
    await factory.image_service.refresh()

    # Update all of the pods to have a status of completed and send an event.
    pod_list = await mock_kubernetes.list_namespaced_pod("nublado")
    for pod in pod_list.items:
        await mark_pod_complete(mock_kubernetes, pod)

    # The prepuller should notice the status change and delete the pods.
    await asyncio.sleep(0.2)
    pod_list = await mock_kubernetes.list_namespaced_pod("nublado")
    assert pod_list.items == []

    # Everything should show as up-to-date because we optimistically update
    # the image service even though it hasn't run again.
    status = factory.image_service.prepull_status()
    for image in status.images.pending:
        if image.tag == "d_2077_10_23":
            assert image.nodes == ["node1", "node2"]

    # There should be no Slack errors from the prepuller updating the image
    # service.
    assert mock_slack.messages == []
