"""Tests for user lab routes."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import ANY

import pytest
from httpx import AsyncClient
from httpx_sse import aconnect_sse
from kubernetes_asyncio.client import (
    ApiException,
    CoreV1Event,
    V1ObjectMeta,
    V1ObjectReference,
    V1ServiceAccount,
)
from safir.metrics import MockEventPublisher
from safir.testing.kubernetes import MockKubernetesApi
from safir.testing.slack import MockSlackWebhook

from controller.config import Config
from controller.constants import DROPDOWN_SENTINEL_VALUE
from controller.dependencies.context import context_dependency
from controller.factory import Factory
from controller.models.domain.gafaelfawr import GafaelfawrUser
from controller.models.domain.kubernetes import PodPhase
from controller.models.v1.lab import LabState

from ..support.config import configure
from ..support.constants import TEST_BASE_URL
from ..support.data import (
    assert_json_output_matches,
    read_input_lab_specification_json,
    read_output_data,
    read_output_json,
)
from ..support.gafaelfawr import get_no_spawn_user
from ..support.kubernetes import objects_to_dicts


async def get_lab_events(
    client: AsyncClient, username: str
) -> list[dict[str, str]]:
    """Listen to a server-sent event stream for lab events.

    Parameters
    ----------
    client
        Client to use to talk to the app.
    username
        Username of user for which to get events.

    Returns
    -------
    dict of str to str or None
        Serialized events read from the server.
    """
    url = f"/nublado/spawner/v1/labs/{username}/events"
    headers = {"X-Auth-Request-User": username}
    async with aconnect_sse(client, "GET", url, headers=headers) as source:
        return [
            {"event": sse.event, "data": sse.data}
            async for sse in source.aiter_sse()
        ]


@pytest.mark.asyncio
async def test_lab_start_stop(
    client: AsyncClient,
    config: Config,
    factory: Factory,
    user: GafaelfawrUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    assert user.quota
    assert user.quota.notebook
    assert context_dependency._process_context
    lab_events = context_dependency._process_context.lab_manager._events
    lab = read_input_lab_specification_json("base", "lab-specification")
    unknown_user_error = {
        "detail": [
            {
                "loc": ["path", "username"],
                "msg": f"Unknown user {user.username}",
                "type": "unknown_user",
            }
        ]
    }

    # No users should have running labs.
    r = await client.get("/nublado/spawner/v1/labs")
    assert r.status_code == 200
    assert r.json() == []
    r = await client.get(f"/nublado/spawner/v1/labs/{user.username}")
    assert r.status_code == 404
    assert r.json() == unknown_user_error
    r = await client.get(
        f"/nublado/spawner/v1/labs/{user.username}/events",
        headers=user.to_headers(),
    )
    assert r.status_code == 404
    assert r.json() == unknown_user_error
    r = await client.delete(
        f"/nublado/spawner/v1/labs/{user.username}", headers=user.to_headers()
    )
    assert r.status_code == 404
    assert r.json() == unknown_user_error

    # Create a lab.
    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={
            "options": {
                "image_list": [DROPDOWN_SENTINEL_VALUE],
                "image_dropdown": [lab.options.image_list],
                "size": [lab.options.size.value],
            },
            "env": lab.env,
        },
        headers=user.to_headers(),
    )
    assert r.status_code == 201
    assert r.headers["Location"] == (
        f"{TEST_BASE_URL}/nublado/spawner/v1/labs/{user.username}"
    )

    # Get events for the lab. The mock Kubernetes layer immediately puts the
    # pod into running status by default, so the event stream should be
    # complete and shouldn't stall waiting for additional events. The content
    # of the events isn't tested here in detail; we'll do that separately.
    r = await client.get(
        f"/nublado/spawner/v1/labs/{user.username}/events",
        headers=user.to_headers(),
    )
    assert r.status_code == 200
    assert "Lab Kubernetes pod started" in r.text

    # The user's lab should now be visible.
    r = await client.get("/nublado/spawner/v1/labs")
    assert r.status_code == 200
    assert r.json() == [user.username]
    r = await client.get(f"/nublado/spawner/v1/labs/{user.username}")
    assert r.status_code == 200
    expected = read_output_json("standard", "lab-status")
    assert r.json() == expected
    lab_state = LabState.model_validate_json(r.text)

    # We should have logged a lab spawn event.
    size = config.lab.get_size_definition(lab.options.size)
    assert isinstance(lab_events.spawn_success, MockEventPublisher)
    lab_events.spawn_success.published.assert_published_all(
        [
            {
                "username": user.username,
                "image": lab_state.options.image,
                "cpu_limit": size.resources.limits.cpu,
                "cpu_request": size.resources.requests.cpu,
                "memory_limit": size.resources.limits.memory,
                "memory_request": size.resources.requests.memory,
                "elapsed": ANY,
            }
        ]
    )
    assert isinstance(lab_events.spawn_failure, MockEventPublisher)
    lab_events.spawn_failure.published.assert_published_all([])

    # Creating the lab again should result in a 409 error.
    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": lab.options.model_dump(), "env": lab.env},
        headers=user.to_headers(),
    )
    assert r.status_code == 409
    assert r.json() == {
        "detail": [
            {
                "msg": f"Lab already exists for {user.username}",
                "type": "lab_exists",
            }
        ]
    }

    # Stop the lab.
    r = await client.delete(f"/nublado/spawner/v1/labs/{user.username}")
    assert r.status_code == 204

    # Now it should be gone again.
    r = await client.get("/nublado/spawner/v1/labs")
    assert r.status_code == 200
    assert r.json() == []
    r = await client.get(f"/nublado/spawner/v1/labs/{user.username}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_spawn_after_failure(
    client: AsyncClient,
    factory: Factory,
    user: GafaelfawrUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    lab = read_input_lab_specification_json("base", "lab-specification")

    # Create a lab.
    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": lab.options.model_dump(), "env": lab.env},
        headers=user.to_headers(),
    )
    assert r.status_code == 201
    assert r.headers["Location"] == (
        f"{TEST_BASE_URL}/nublado/spawner/v1/labs/{user.username}"
    )
    await asyncio.sleep(0)

    # Change the pod phase.
    name = f"{user.username}-nb"
    namespace = f"userlabs-{user.username}"
    await mock_kubernetes.patch_namespaced_pod_status(
        name,
        namespace,
        [
            {
                "op": "replace",
                "path": "/status/phase",
                "value": PodPhase.FAILED.value,
            }
        ],
    )
    await asyncio.sleep(0.1)

    # Create the lab again. This should not fail with a conflict; instead, it
    # should delete the old lab and then create a new one.
    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": lab.options.model_dump(), "env": lab.env},
        headers=user.to_headers(),
    )
    assert r.status_code == 201
    assert r.headers["Location"] == (
        f"{TEST_BASE_URL}/nublado/spawner/v1/labs/{user.username}"
    )
    await asyncio.sleep(0)
    pod = await mock_kubernetes.read_namespaced_pod(name, namespace)
    assert pod.status.phase == PodPhase.RUNNING.value

    # Get the events and look for the lab recreation events.
    expected_events = read_output_json("standard", "lab-recreate-events")
    assert await get_lab_events(client, user.username) == expected_events


@pytest.mark.asyncio
async def test_multiple_delete(
    client: AsyncClient,
    factory: Factory,
    user: GafaelfawrUser,
    mock_slack: MockSlackWebhook,
) -> None:
    lab = read_input_lab_specification_json("base", "lab-specification")

    # Create a lab.
    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": lab.options.model_dump(), "env": lab.env},
        headers=user.to_headers(),
    )
    assert r.status_code == 201
    await asyncio.sleep(0.1)

    # Now, attempt to delete it five times simultaneously. Every one of these
    # should either return 204 (if they made it into the queue before any of
    # them finish) or 404 (if they lost the race).
    #
    # Adding a way to delay deletion to the mock would make this test more
    # reliable, but in practice all five deletes normally make it to the wait
    # stage before the delete finishes.
    results = await asyncio.gather(
        client.delete(f"/nublado/spawner/v1/labs/{user.username}"),
        client.delete(f"/nublado/spawner/v1/labs/{user.username}"),
        client.delete(f"/nublado/spawner/v1/labs/{user.username}"),
        client.delete(f"/nublado/spawner/v1/labs/{user.username}"),
        client.delete(f"/nublado/spawner/v1/labs/{user.username}"),
    )
    for r in results:
        assert r.status_code in (204, 404)

    # Running delete one more time should always result in a 404.
    r = await client.delete(f"/nublado/spawner/v1/labs/{user.username}")
    assert r.status_code == 404

    # None of this should have produced Slack error messages.
    assert mock_slack.messages == []


@pytest.mark.asyncio
async def test_delayed_spawn(
    client: AsyncClient,
    factory: Factory,
    user: GafaelfawrUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    lab = read_input_lab_specification_json("base", "lab-specification")
    mock_kubernetes.initial_pod_phase = PodPhase.PENDING.value

    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": lab.options.model_dump(), "env": lab.env},
        headers=user.to_headers(),
    )
    assert r.status_code == 201
    await asyncio.sleep(0.1)
    r = await client.get(f"/nublado/spawner/v1/labs/{user.username}")
    assert r.status_code == 200
    assert r.json()["status"] == "pending"

    # Attempting to spawn another lab should produce a 409 Conflict error.
    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": lab.options.model_dump(), "env": lab.env},
        headers=user.to_headers(),
    )
    assert r.status_code == 409

    # Start event listeners to collect pod spawn events. We should be able to
    # listen for events for the same pod any number of times, and all of the
    # listeners should see the same events.
    listeners = [
        asyncio.create_task(get_lab_events(client, user.username)),
        asyncio.create_task(get_lab_events(client, user.username)),
        asyncio.create_task(get_lab_events(client, user.username)),
    ]

    # Add a few events.
    namespace = f"userlabs-{user.username}"
    name = f"{user.username}-nb"
    await mock_kubernetes.read_namespaced_pod(name, namespace)
    event = CoreV1Event(
        metadata=V1ObjectMeta(name=f"{name}-1", namespace=namespace),
        message="Autoscaling cluster for reasons",
        involved_object=V1ObjectReference(
            kind="Pod", name=name, namespace=namespace
        ),
    )
    await mock_kubernetes.create_namespaced_event(namespace, event)
    event = CoreV1Event(
        metadata=V1ObjectMeta(name=f"{name}-2", namespace=namespace),
        message="Mounting all the things",
        involved_object=V1ObjectReference(
            kind="Pod", name=name, namespace=namespace
        ),
    )
    await mock_kubernetes.create_namespaced_event(namespace, event)

    # Change the pod status to running. Do not create another event;
    # apparently Kubernetes doesn't create events when pods change phase.
    await asyncio.sleep(0.1)
    await mock_kubernetes.patch_namespaced_pod_status(
        name,
        namespace,
        [
            {
                "op": "replace",
                "path": "/status/phase",
                "value": PodPhase.RUNNING.value,
            }
        ],
    )

    # The listeners should now complete successfully and we should see
    # appropriate events.
    event_lists = await asyncio.gather(*listeners)
    expected_events = read_output_json("standard", "lab-spawn-events")
    expected_events = [
        *expected_events[:-1],
        *[
            {
                "data": json.dumps(
                    {
                        "message": "Autoscaling cluster for reasons",
                        "progress": 35,
                    }
                ),
                "event": "info",
            },
            {
                "data": json.dumps(
                    {
                        "message": "Mounting all the things",
                        "progress": 48,
                    }
                ),
                "event": "info",
            },
        ],
        *expected_events[-1:],
    ]
    for event_list in event_lists:
        assert event_list == expected_events

    # And the pod should now be running.
    r = await client.get(f"/nublado/spawner/v1/labs/{user.username}")
    assert r.status_code == 200
    assert r.json()["status"] == "running"

    # Retrieving events repeatedly should just keep returning the same event
    # list and immediately complete.
    events = await get_lab_events(client, user.username)
    assert events == expected_events


@pytest.mark.asyncio
async def test_abort_spawn(
    client: AsyncClient,
    factory: Factory,
    user: GafaelfawrUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    lab = read_input_lab_specification_json("base", "lab-specification")
    mock_kubernetes.initial_pod_phase = PodPhase.PENDING.value

    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": lab.options.model_dump(), "env": lab.env},
        headers=user.to_headers(),
    )
    assert r.status_code == 201
    await asyncio.sleep(0)
    r = await client.get(f"/nublado/spawner/v1/labs/{user.username}")
    assert r.status_code == 200
    assert r.json()["status"] == "pending"

    # Deleting the lab while it is spawning should abort the spawn and clean
    # up any remnants of the lab.
    r = await client.delete(f"/nublado/spawner/v1/labs/{user.username}")
    assert r.status_code == 204
    r = await client.get(f"/nublado/spawner/v1/labs/{user.username}")
    assert r.status_code == 404
    with pytest.raises(ApiException) as excinfo:
        await mock_kubernetes.read_namespace(f"userlabs-{user.username}")
    assert excinfo.value.status == 404


@pytest.mark.asyncio
async def test_spawn_after_terminate(
    client: AsyncClient,
    factory: Factory,
    user: GafaelfawrUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    lab = read_input_lab_specification_json("base", "lab-specification")
    mock_kubernetes.initial_pod_phase = PodPhase.SUCCEEDED.value

    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": lab.options.model_dump(), "env": lab.env},
        headers=user.to_headers(),
    )
    assert r.status_code == 201
    await asyncio.sleep(0.1)

    # We should now be able to spawn the lab again, and the controller should
    # quietly delete the terminated lab and create a new one.
    mock_kubernetes.initial_pod_phase = PodPhase.RUNNING.value
    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": lab.options.model_dump(), "env": lab.env},
        headers=user.to_headers(),
    )
    assert r.status_code == 201
    await asyncio.sleep(0.1)
    r = await client.get(f"/nublado/spawner/v1/labs/{user.username}")
    assert r.status_code == 200
    assert r.json()["status"] == "running"


@pytest.mark.asyncio
async def test_lab_objects(
    client: AsyncClient,
    config: Config,
    user: GafaelfawrUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    lab = read_input_lab_specification_json("base", "lab-specification")

    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": lab.options.model_dump(), "env": lab.env},
        headers=user.to_headers(),
    )
    assert r.status_code == 201
    await asyncio.sleep(0)

    # When checking all of the objects, strip out resource versions, since
    # those are added by Kubernetes (and the Kubernetes mock) and are not
    # meaningful to compare.
    namespace = f"{config.lab.namespace_prefix}-{user.username}"
    objects = mock_kubernetes.get_namespace_objects_for_test(namespace)
    seen = objects_to_dicts(objects)
    assert_json_output_matches(seen, "standard", "lab-objects")


@pytest.mark.asyncio
async def test_errors(client: AsyncClient, user: GafaelfawrUser) -> None:
    lab = read_input_lab_specification_json("base", "lab-specification")

    # Wrong user.
    r = await client.post(
        "/nublado/spawner/v1/labs/otheruser/create",
        json={"options": lab.options.model_dump(), "env": lab.env},
        headers=user.to_headers(),
    )
    assert r.status_code == 403
    assert r.json() == {
        "detail": [{"msg": "Permission denied", "type": "permission_denied"}]
    }
    r = await client.get(
        "/nublado/spawner/v1/labs/otheruser/events", headers=user.to_headers()
    )
    assert r.status_code == 403
    assert r.json() == {
        "detail": [{"msg": "Permission denied", "type": "permission_denied"}]
    }

    # Invalid token.
    r = await client.post(
        "/nublado/spawner/v1/labs/otheruser/create",
        json={"options": lab.options.model_dump(), "env": lab.env},
        headers={
            "X-Auth-Request-Token": "some-invalid-token",
            "X-Auth-Request-User": user.username,
        },
    )
    assert r.status_code == 401
    assert r.json() == {
        "detail": [{"msg": "User token is invalid", "type": "invalid_token"}]
    }

    # Test passing a reference with no tag.
    options = lab.options.model_dump()
    options["image_list"] = "lighthouse.ceres/library/sketchbook"
    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": options, "env": lab.env},
        headers=user.to_headers(),
    )
    assert r.status_code == 422
    msg = 'Docker reference "lighthouse.ceres/library/sketchbook" has no tag'
    assert r.json() == {
        "detail": [
            {
                "loc": ["body", "options", "image_list"],
                "msg": msg,
                "type": "invalid_docker_reference",
            }
        ]
    }

    # The same but in image_dropdown.
    options = lab.options.model_dump()
    options["image_list"] = DROPDOWN_SENTINEL_VALUE
    options["image_dropdown"] = "lighthouse.ceres/library/sketchbook"
    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": options, "env": lab.env},
        headers=user.to_headers(),
    )
    assert r.status_code == 422
    msg = 'Docker reference "lighthouse.ceres/library/sketchbook" has no tag'
    assert r.json() == {
        "detail": [
            {
                "loc": ["body", "options", "image_dropdown"],
                "msg": msg,
                "type": "invalid_docker_reference",
            }
        ]
    }

    # Test asking for an image that doesn't exist.
    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={
            "options": {"image_tag": "unknown", "size": "small"},
            "env": lab.env,
        },
        headers=user.to_headers(),
    )
    assert r.status_code == 400
    assert r.json() == {
        "detail": [
            {
                "loc": ["body", "options", "image_tag"],
                "msg": 'Docker tag "unknown" not found',
                "type": "unknown_image",
            }
        ]
    }

    # Test requesting a lab size that doesn't exist.
    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={
            "options": {"image_tag": "recommended", "size": "gargantuan"},
            "env": lab.env,
        },
        headers=user.to_headers(),
    )
    assert r.status_code == 422
    assert r.json() == {
        "detail": [
            {
                "loc": ["body", "options", "size"],
                "msg": 'Invalid lab size "gargantuan"',
                "type": "invalid_lab_size",
            }
        ]
    }

    # Test requesting a lab size too large for the user's quota.
    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={
            "options": {"image_tag": "recommended", "size": "huge"},
            "env": lab.env,
        },
        headers=user.to_headers(),
    )
    assert r.status_code == 403
    assert r.json() == {
        "detail": [
            {
                "loc": ["body", "options", "size"],
                "msg": "Insufficient quota to spawn requested lab",
                "type": "insufficient_quota",
            }
        ]
    }


@pytest.mark.asyncio
async def test_spawn_errors(
    client: AsyncClient,
    config: Config,
    user: GafaelfawrUser,
    mock_kubernetes: MockKubernetesApi,
    mock_slack: MockSlackWebhook,
) -> None:
    lab = read_input_lab_specification_json("base", "lab-specification")
    apis_to_fail = set()

    def callback(method: str, *args: Any) -> None:
        if method in apis_to_fail:
            raise ApiException(status=400, reason="Something bad happened")

    mock_kubernetes.error_callback = callback

    # For each of the various Kubernetes calls that might fail, test that the
    # failure is caught, results in a correct failure event with a correct
    # message, and leaves the lab in a failed state.
    possible_errors = [
        (
            "create_namespace",
            "creating namespace",
            "Namespace",
            "userlabs-rachel",
        ),
        (
            "read_namespaced_secret",
            "reading object",
            "Secret",
            "nublado/extra-secret",
        ),
        (
            "create_namespaced_secret",
            "creating object",
            "Secret",
            "userlabs-rachel/rachel-nb",
        ),
        (
            "create_namespaced_config_map",
            "creating object",
            "ConfigMap",
            "userlabs-rachel/rachel-nb-env",
        ),
        (
            "create_namespaced_network_policy",
            "creating object",
            "NetworkPolicy",
            "userlabs-rachel/rachel-nb",
        ),
        (
            "create_namespaced_resource_quota",
            "creating object",
            "ResourceQuota",
            "userlabs-rachel/rachel-nb",
        ),
        (
            "create_namespaced_service",
            "creating object",
            "Service",
            "userlabs-rachel/lab",
        ),
        (
            "create_namespaced_pod",
            "creating object",
            "Pod",
            "userlabs-rachel/rachel-nb",
        ),
    ]
    for api, error, kind, obj in possible_errors:
        apis_to_fail = {api}
        r = await client.post(
            f"/nublado/spawner/v1/labs/{user.username}/create",
            json={"options": lab.options.model_dump(), "env": lab.env},
            headers=user.to_headers(),
        )
        assert r.status_code == 201
        events = await get_lab_events(client, user.username)
        error_msg = f"Error {error} ({kind} {obj}, status 400)"
        assert events[-2] == {
            "data": json.dumps(
                {"message": f"{error_msg}: Something bad happened"}
            ),
            "event": "error",
        }
        assert events[-1] == {
            "data": json.dumps({"message": "Lab spawn failed"}),
            "event": "failed",
        }
        assert mock_slack.messages == [
            {
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "text": f"Error in Nublado: {error_msg}",
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
                                "text": "*User*\nrachel",
                                "type": "mrkdwn",
                                "verbatim": True,
                            },
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
                            "text": f"*Object*\n{kind} {obj}",
                            "type": "mrkdwn",
                            "verbatim": True,
                        },
                    },
                    {
                        "type": "section",
                        "text": {
                            "text": (
                                "*Error*\n```\nSomething bad happened\n```"
                            ),
                            "type": "mrkdwn",
                            "verbatim": True,
                        },
                    },
                    {"type": "divider"},
                ]
            },
        ]
        mock_slack.messages = []
        r = await client.get(f"/nublado/spawner/v1/labs/{user.username}")
        assert r.status_code == 200
        assert r.json()["status"] == "failed"
        r = await client.delete(f"/nublado/spawner/v1/labs/{user.username}")
        assert r.status_code == 204

    # Check that we posted metrics events for the failures.
    assert context_dependency._process_context
    lab_events = context_dependency._process_context.lab_manager._events
    size = config.lab.get_size_definition(lab.options.size)
    assert isinstance(lab_events.spawn_success, MockEventPublisher)
    lab_events.spawn_success.published.assert_published_all([])
    assert isinstance(lab_events.spawn_failure, MockEventPublisher)
    failure = {
        "username": user.username,
        "image": ANY,
        "cpu_limit": size.resources.limits.cpu,
        "cpu_request": size.resources.requests.cpu,
        "memory_limit": size.resources.limits.memory,
        "memory_request": size.resources.requests.memory,
        "elapsed": ANY,
    }
    failure_events = [failure for e in possible_errors]
    lab_events.spawn_failure.published.assert_published_all(failure_events)


@pytest.mark.asyncio
async def test_homedir_schema(
    client: AsyncClient,
    user: GafaelfawrUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    """Check that the home directory is constructed correctly.

    Earlier versions had a bug where the working directory for the spawned pod
    was always :file:`/home/{username}` even if another home directory rule
    was set.
    """
    config = await configure("homedir-schema")
    lab = read_input_lab_specification_json("base", "lab-specification")

    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": lab.options.model_dump(), "env": lab.env},
        headers=user.to_headers(),
    )
    assert r.status_code == 201
    await asyncio.sleep(0)

    config_map = await mock_kubernetes.read_namespaced_config_map(
        f"{user.username}-nb-nss",
        f"{config.lab.namespace_prefix}-{user.username}",
    )
    expected_passwd = read_output_data("homedir-schema", "passwd")
    assert config_map.data["passwd"] == expected_passwd

    pod = await mock_kubernetes.read_namespaced_pod(
        f"{user.username}-nb",
        f"{config.lab.namespace_prefix}-{user.username}",
    )
    expected_homedir = f"/u/home/{user.username[0]}/{user.username}/jhome"
    for container in pod.spec.containers:
        assert container.working_dir == expected_homedir


@pytest.mark.asyncio
async def test_tmp_on_disk(
    client: AsyncClient,
    user: GafaelfawrUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    """Check that /tmp is constructed correctly if set to use disk rather
    than memory.
    """
    config = await configure("tmp-disk")
    lab = read_input_lab_specification_json("base", "lab-specification")

    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": lab.options.model_dump(), "env": lab.env},
        headers=user.to_headers(),
    )
    assert r.status_code == 201
    await asyncio.sleep(0)

    pod = await mock_kubernetes.read_namespaced_pod(
        f"{user.username}-nb",
        f"{config.lab.namespace_prefix}-{user.username}",
    )
    for vol in pod.spec.volumes:
        if vol.empty_dir is None:
            continue
        assert vol.empty_dir.medium is None
        return


@pytest.mark.asyncio
async def test_alternate_paths(
    client: AsyncClient,
    user: GafaelfawrUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    """Check changes to command, config, and runtime mount paths."""
    config = await configure("changed-path")
    lab = read_input_lab_specification_json("base", "lab-specification")

    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": lab.options.model_dump(), "env": lab.env},
        headers=user.to_headers(),
    )
    assert r.status_code == 201
    await asyncio.sleep(0)
    pod = await mock_kubernetes.read_namespaced_pod(
        f"{user.username}-nb",
        f"{config.lab.namespace_prefix}-{user.username}",
    )
    container = pod.spec.containers[0]
    assert container.args == ["/usr/local/share/jupyterlab/runlab"]
    secrets_mount = next(
        x for x in container.volume_mounts if x.name == "secrets"
    )
    assert secrets_mount.mount_path == "/etc/nublado/secrets"
    config_map = await mock_kubernetes.read_namespaced_config_map(
        f"{user.username}-nb-env",
        f"{config.lab.namespace_prefix}-{user.username}",
    )
    config_dir = config_map.data["JUPYTERLAB_CONFIG_DIR"]
    assert config_dir == "/usr/local/share/jupyterlab"


@pytest.mark.asyncio
async def test_extra_annotations(
    client: AsyncClient,
    user: GafaelfawrUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    """Check that the pod picks up extra annotations set in the config."""
    config = await configure("extra-annotations")
    lab = read_input_lab_specification_json("base", "lab-specification")

    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": lab.options.model_dump(), "env": lab.env},
        headers=user.to_headers(),
    )
    assert r.status_code == 201
    await asyncio.sleep(0)

    namespace = f"{config.lab.namespace_prefix}-{user.username}"
    pod_name = f"{user.username}-nb"
    pod = await mock_kubernetes.read_namespaced_pod(pod_name, namespace)
    for key, value in config.lab.extra_annotations.items():
        assert pod.metadata.annotations[key] == value


@pytest.mark.asyncio
async def test_quota_no_spawn(client: AsyncClient) -> None:
    """Check that spawning is denied for a user blocked by quota."""
    lab = read_input_lab_specification_json("base", "lab-specification")
    _, user = get_no_spawn_user()

    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": lab.options.model_dump(), "env": lab.env},
        headers=user.to_headers(),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_wait_for_sa(
    client: AsyncClient,
    factory: Factory,
    user: GafaelfawrUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    """Test waiting for the default service account during lab creation."""
    lab = read_input_lab_specification_json("base", "lab-specification")

    # Clear the callback added by the fixture so that we do not automatically
    # create the default service account.
    mock_kubernetes.register_create_hook_for_test("Namespace", None)

    # Create the lab and confirm that it entered pending state.
    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": lab.options.model_dump(), "env": lab.env},
        headers=user.to_headers(),
    )
    assert r.status_code == 201
    await asyncio.sleep(0.1)
    r = await client.get(f"/nublado/spawner/v1/labs/{user.username}")
    assert r.status_code == 200
    assert r.json()["status"] == "pending"

    # Create the service account, which should cause the lab to complete.
    namespace = f"userlabs-{user.username}"
    await mock_kubernetes.create_namespaced_service_account(
        namespace,
        V1ServiceAccount(
            metadata=V1ObjectMeta(name="default", namespace=namespace)
        ),
    )
    await asyncio.sleep(0.1)
    r = await client.get(f"/nublado/spawner/v1/labs/{user.username}")
    assert r.status_code == 200
    assert r.json()["status"] == "running"
