"""Tests for user lab routes."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
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
)
from safir.testing.kubernetes import MockKubernetesApi, strip_none
from safir.testing.slack import MockSlackWebhook

from jupyterlabcontroller.config import Config
from jupyterlabcontroller.constants import DROPDOWN_SENTINEL_VALUE
from jupyterlabcontroller.factory import Factory
from jupyterlabcontroller.models.domain.kubernetes import KubernetesPodPhase

from ..settings import TestObjectFactory
from ..support.constants import TEST_BASE_URL


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
    events = []
    url = f"/nublado/spawner/v1/labs/{username}/events"
    headers = {"X-Auth-Request-User": username}
    async with aconnect_sse(client, "GET", url, headers=headers) as source:
        async for sse in source.aiter_sse():
            events.append({"event": sse.event, "data": sse.data})
    return events


@pytest.mark.asyncio
async def test_lab_start_stop(
    client: AsyncClient,
    factory: Factory,
    obj_factory: TestObjectFactory,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    token, user = obj_factory.get_user()
    lab = obj_factory.labspecs[0]
    size_manager = factory.create_size_manager()
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
        headers={"X-Auth-Request-User": user.username},
    )
    assert r.status_code == 404
    assert r.json() == unknown_user_error
    r = await client.delete(
        f"/nublado/spawner/v1/labs/{user.username}",
        headers={"X-Auth-Request-User": user.username},
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
        headers={
            "X-Auth-Request-Token": token,
            "X-Auth-Request-User": user.username,
        },
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
        headers={"X-Auth-Request-User": user.username},
    )
    assert r.status_code == 200
    assert "Lab Kubernetes pod started" in r.text

    # The user's lab should now be visible.
    r = await client.get("/nublado/spawner/v1/labs")
    assert r.status_code == 200
    assert r.json() == [user.username]
    r = await client.get(f"/nublado/spawner/v1/labs/{user.username}")
    assert r.status_code == 200
    expected_resources = size_manager.resources(lab.options.size)
    expected_options = lab.options.dict()
    expected_options["image_dropdown"] = expected_options["image_list"]
    expected_options["image_list"] = None
    expected = {
        "env": lab.env,
        "gid": user.gid,
        "groups": user.dict()["groups"],
        "internal_url": (
            f"http://lab.userlabs-{user.username}:8888/nb/user/rachel/"
        ),
        "name": user.name,
        "options": expected_options,
        "pod": "present",
        "quota": {"api": {}, "notebook": {"cpu": 9.0, "memory": 27.0}},
        "resources": expected_resources.dict(),
        "status": "running",
        "uid": user.uid,
        "username": user.username,
    }
    assert r.json() == expected

    # Creating the lab again should result in a 409 error.
    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": lab.options.dict(), "env": lab.env},
        headers={
            "X-Auth-Request-Token": token,
            "X-Auth-Request-User": user.username,
        },
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

    # Change the pod phase. This should throw the lab into a failed state.
    name = f"nb-{user.username}"
    namespace = f"userlabs-{user.username}"
    pod = await mock_kubernetes.read_namespaced_pod(name, namespace)
    pod.status.phase = KubernetesPodPhase.FAILED.value
    r = await client.get(f"/nublado/spawner/v1/labs/{user.username}")
    assert r.status_code == 200
    expected["status"] = "failed"
    assert r.json() == expected

    # Delete the pod out from under the controller. This should also change
    # the pod status.
    await mock_kubernetes.delete_namespaced_pod(name, namespace)
    r = await client.get(f"/nublado/spawner/v1/labs/{user.username}")
    assert r.status_code == 200
    expected["pod"] = "missing"
    assert r.json() == expected

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
    obj_factory: TestObjectFactory,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    token, user = obj_factory.get_user()
    lab = obj_factory.labspecs[0]

    # Create a lab.
    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": lab.options.dict(), "env": lab.env},
        headers={
            "X-Auth-Request-Token": token,
            "X-Auth-Request-User": user.username,
        },
    )
    assert r.status_code == 201
    assert r.headers["Location"] == (
        f"{TEST_BASE_URL}/nublado/spawner/v1/labs/{user.username}"
    )

    # Change the pod phase. This should throw the lab into a failed state.
    name = f"nb-{user.username}"
    namespace = f"userlabs-{user.username}"
    pod = await mock_kubernetes.read_namespaced_pod(name, namespace)
    pod.status.phase = KubernetesPodPhase.FAILED.value
    r = await client.get(f"/nublado/spawner/v1/labs/{user.username}")
    assert r.status_code == 200
    assert r.json()["status"] == "failed"

    # Create the lab again. This should not fail with a conflict; instead, it
    # should delete the old lab and then create a new one.
    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": lab.options.dict(), "env": lab.env},
        headers={
            "X-Auth-Request-Token": token,
            "X-Auth-Request-User": user.username,
        },
    )
    assert r.status_code == 201
    assert r.headers["Location"] == (
        f"{TEST_BASE_URL}/nublado/spawner/v1/labs/{user.username}"
    )
    pod = await mock_kubernetes.read_namespaced_pod(name, namespace)
    assert pod.status.phase == KubernetesPodPhase.RUNNING.value

    # Get the events and look for the lab recreation events.
    r = await client.get(
        f"/nublado/spawner/v1/labs/{user.username}/events",
        headers={"X-Auth-Request-User": user.username},
    )
    assert r.status_code == 200
    assert f"Deleting existing failed lab for {user.username}" in r.text
    assert f"Deleting namespace for {user.username}" in r.text


@pytest.mark.asyncio
async def test_delayed_spawn(
    client: AsyncClient,
    factory: Factory,
    mock_kubernetes: MockKubernetesApi,
    obj_factory: TestObjectFactory,
    std_result_dir: Path,
) -> None:
    token, user = obj_factory.get_user()
    lab = obj_factory.labspecs[0]
    mock_kubernetes.initial_pod_phase = KubernetesPodPhase.PENDING.value

    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": lab.options.dict(), "env": lab.env},
        headers={
            "X-Auth-Request-Token": token,
            "X-Auth-Request-User": user.username,
        },
    )
    assert r.status_code == 201
    r = await client.get(f"/nublado/spawner/v1/labs/{user.username}")
    assert r.status_code == 200
    assert r.json()["status"] == "pending"

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
    name = f"nb-{user.username}"
    pod = await mock_kubernetes.read_namespaced_pod(name, namespace)
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
    pod.status.phase = KubernetesPodPhase.RUNNING.value

    # The listeners should now complete successfully and we should see
    # appropriate events.
    event_lists = await asyncio.gather(*listeners)
    with (std_result_dir / "pod-events.json").open("r") as f:
        expected_events = json.load(f)
    expected_events = (
        expected_events[:-1]
        + [
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
        ]
        + expected_events[-1:]
    )
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
async def test_lab_objects(
    client: AsyncClient,
    config: Config,
    mock_kubernetes: MockKubernetesApi,
    obj_factory: TestObjectFactory,
    std_result_dir: Path,
) -> None:
    token, user = obj_factory.get_user()
    lab = obj_factory.labspecs[0]

    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": lab.options.dict(), "env": lab.env},
        headers={
            "X-Auth-Request-Token": token,
            "X-Auth-Request-User": user.username,
        },
    )
    assert r.status_code == 201

    namespace = f"{config.lab.namespace_prefix}-{user.username}"
    objects = mock_kubernetes.get_namespace_objects_for_test(namespace)
    with (std_result_dir / "lab-objects.json").open("r") as f:
        expected = json.load(f)
    assert [strip_none(o.to_dict()) for o in objects] == expected


@pytest.mark.asyncio
async def test_errors(
    client: AsyncClient, obj_factory: TestObjectFactory
) -> None:
    token, user = obj_factory.get_user()
    lab = obj_factory.labspecs[0]

    # Wrong user.
    r = await client.post(
        "/nublado/spawner/v1/labs/otheruser/create",
        json={"options": lab.options.dict(), "env": lab.env},
        headers={
            "X-Auth-Request-Token": token,
            "X-Auth-Request-User": user.username,
        },
    )
    assert r.status_code == 403
    assert r.json() == {
        "detail": [{"msg": "Permission denied", "type": "permission_denied"}]
    }
    r = await client.get(
        "/nublado/spawner/v1/labs/otheruser/events",
        headers={"X-Auth-Request-User": user.username},
    )
    assert r.status_code == 403
    assert r.json() == {
        "detail": [{"msg": "Permission denied", "type": "permission_denied"}]
    }

    # Invalid token.
    r = await client.post(
        "/nublado/spawner/v1/labs/otheruser/create",
        json={"options": lab.options.dict(), "env": lab.env},
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
    options = lab.options.dict()
    options["image_list"] = "lighthouse.ceres/library/sketchbook"
    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": options, "env": lab.env},
        headers={
            "X-Auth-Request-Token": token,
            "X-Auth-Request-User": user.username,
        },
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
    options = lab.options.dict()
    options["image_list"] = DROPDOWN_SENTINEL_VALUE
    options["image_dropdown"] = "lighthouse.ceres/library/sketchbook"
    r = await client.post(
        f"/nublado/spawner/v1/labs/{user.username}/create",
        json={"options": options, "env": lab.env},
        headers={
            "X-Auth-Request-Token": token,
            "X-Auth-Request-User": user.username,
        },
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
        headers={
            "X-Auth-Request-Token": token,
            "X-Auth-Request-User": user.username,
        },
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


@pytest.mark.asyncio
async def test_spawn_errors(
    client: AsyncClient,
    obj_factory: TestObjectFactory,
    mock_kubernetes: MockKubernetesApi,
    mock_slack: MockSlackWebhook,
) -> None:
    token, user = obj_factory.get_user()
    lab = obj_factory.labspecs[0]
    apis_to_fail = {"read_namespaced_secret"}

    def callback(method: str, *args: Any) -> None:
        if method in apis_to_fail:
            raise ApiException(status=400, reason="Something bad happened")

    mock_kubernetes.error_callback = callback

    # For each of the various Kubernetes calls that might fail, test that the
    # failure is caught, results in a correct failure event with a correct
    # message, and leaves the lab in a failed state.
    possible_errors = [
        ("create_namespace", "creating user namespace", "userlabs-rachel"),
        (
            "read_namespaced_secret",
            "reading secret",
            "userlabs/nublado-secret",
        ),
        (
            "create_namespaced_secret",
            "creating secret",
            "userlabs-rachel/nb-rachel",
        ),
        (
            "create_namespaced_config_map",
            "creating config map",
            "userlabs-rachel/nb-rachel-nss",
        ),
        (
            "create_namespaced_network_policy",
            "creating network policy",
            "userlabs-rachel/nb-rachel-env",
        ),
        (
            "create_namespaced_resource_quota",
            "creating resource quota",
            "userlabs-rachel/nb-rachel",
        ),
        (
            "create_namespaced_service",
            "creating service",
            "userlabs-rachel/lab",
        ),
        ("create_namespaced_pod", "creating pod", "userlabs-rachel/nb-rachel"),
    ]
    for api, error, obj in possible_errors:
        apis_to_fail = {api}
        r = await client.post(
            f"/nublado/spawner/v1/labs/{user.username}/create",
            json={"options": lab.options.dict(), "env": lab.env},
            headers={
                "X-Auth-Request-Token": token,
                "X-Auth-Request-User": user.username,
            },
        )
        assert r.status_code == 201
        events = await get_lab_events(client, user.username)
        error = f"Error {error} ({obj}, status 400)"
        assert events[-2] == {
            "data": json.dumps(
                {"message": f"{error}: Something bad happened"}
            ),
            "event": "error",
        }
        assert events[-1] == {
            "data": json.dumps({"message": "Lab creation failed"}),
            "event": "failed",
        }
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
                                "text": "*User*\nrachel",
                                "type": "mrkdwn",
                                "verbatim": True,
                            },
                            {
                                "text": f"*Object*\n{obj}",
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
        r = await client.delete(f"/nublado/spawner/v1/labs/{user.username}")
        assert r.status_code == 204
