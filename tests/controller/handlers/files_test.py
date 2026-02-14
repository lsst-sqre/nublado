"""Tests for user lab routes."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import ANY

import pytest
from httpx import AsyncClient
from kubernetes_asyncio.client import ApiException
from safir.models import ErrorModel
from safir.testing.kubernetes import MockKubernetesApi
from safir.testing.slack import MockSlackWebhook

from nublado.controller.models.domain.kubernetes import PodPhase

from ...support.config import configure
from ...support.data import NubladoData
from ...support.fileserver import (
    create_ingress_for_user,
    create_working_ingress_for_user,
    delete_ingress_for_user,
)
from ...support.gafaelfawr import GafaelfawrTestUser


@pytest.mark.timeout(5)
@pytest.mark.asyncio
async def test_create_delete(
    *,
    client: AsyncClient,
    data: NubladoData,
    user: GafaelfawrTestUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    config = await configure(data, "fileserver", mock_kubernetes)
    assert config.fileserver.enabled
    username = user.username
    namespace = config.fileserver.namespace

    # No fileservers yet.
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.status_code == 200
    assert r.json() == []
    r = await client.get(
        "/nublado/fileserver/v1/user-status", headers=user.to_test_headers()
    )
    assert r.status_code == 404
    r = await client.get(f"/nublado/fileserver/v1/users/{username}")
    assert r.status_code == 404

    # Start a user fileserver. Pre-create an Ingress to match the
    # GafaelfawrIngress so that the creation succeeds.
    await create_working_ingress_for_user(mock_kubernetes, username, namespace)
    r = await client.get("/files", headers=user.to_test_headers())
    assert r.status_code == 200
    data.assert_text_matches(
        r.text, "controller/fileserver/output/fileserver.html"
    )

    # Check that it has showed up, via the user status and admin routes.
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == [username]
    r = await client.get(
        "/nublado/fileserver/v1/user-status", headers=user.to_test_headers()
    )
    assert r.status_code == 200
    assert r.json() == {"running": True}
    r = await client.get(f"/nublado/fileserver/v1/users/{username}")
    assert r.status_code == 200
    assert r.json() == {"running": True}

    # Request it again; should detect that there is a user fileserver and
    # return immediately without actually doing anything.
    r = await client.get("/files", headers=user.to_test_headers())
    assert r.status_code == 200
    data.assert_text_matches(
        r.text, "controller/fileserver/output/fileserver.html"
    )
    r = await client.get(
        "/nublado/fileserver/v1/user-status", headers=user.to_test_headers()
    )
    assert r.status_code == 200
    assert r.json() == {"running": True}

    # Wait for the reconcile time and then check again to make sure reconcile
    # didn't incorrectly remove it (a bug in versions <= 8.8.9).
    await asyncio.sleep(config.fileserver.reconcile_interval.total_seconds())
    r = await client.get(
        "/nublado/fileserver/v1/user-status", headers=user.to_test_headers()
    )
    assert r.status_code == 200
    assert r.json() == {"running": True}

    # Remove it, via an admin route. Pre-delete the Ingress since Kubernetes
    # won't do it automatically for us during test.
    await delete_ingress_for_user(mock_kubernetes, username, namespace)
    r = await client.delete(f"/nublado/fileserver/v1/users/{username}")
    assert r.status_code == 204
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.status_code == 200
    assert r.json() == []
    r = await client.get(
        "/nublado/fileserver/v1/user-status", headers=user.to_test_headers()
    )
    assert r.status_code == 404
    r = await client.get(f"/nublado/fileserver/v1/users/{username}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_file_server_objects(
    *,
    client: AsyncClient,
    data: NubladoData,
    user: GafaelfawrTestUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    config = await configure(data, "fileserver", mock_kubernetes)
    assert config.fileserver.enabled
    username = user.username
    namespace = config.fileserver.namespace

    # Start a user fileserver. Pre-create an Ingress to match the
    # GafaelfawrIngress so that the creation succeeds.
    await create_working_ingress_for_user(mock_kubernetes, username, namespace)
    r = await client.get("/files", headers=user.to_test_headers())
    assert r.status_code == 200

    # Compare all of the objects in the file server namespace to the expected
    # results.
    objects = mock_kubernetes.get_namespace_objects_for_test(namespace)
    data.assert_kubernetes_matches(
        objects, "controller/fileserver/output/fileserver-objects"
    )


@pytest.mark.asyncio
async def test_cleanup_on_pod_exit(
    *,
    client: AsyncClient,
    data: NubladoData,
    user: GafaelfawrTestUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    config = await configure(data, "fileserver", mock_kubernetes)
    assert config.fileserver.enabled
    username = user.username
    namespace = config.fileserver.namespace

    # Start a user fileserver. Pre-create an Ingress to match the
    # GafaelfawrIngress so that the creation succeeds.
    await create_working_ingress_for_user(mock_kubernetes, username, namespace)
    r = await client.get("/files", headers=user.to_test_headers())
    assert r.status_code == 200

    # On a regular cluster, the fileserver takes a timeout as an argument and
    # exits after it's been idle that long. Simulate this by finding the pod
    # and changing its status to indicate it exited.
    pods = await mock_kubernetes.list_namespaced_pod(
        namespace, label_selector=f"job-name={username}-fs"
    )
    assert len(pods.items) == 1
    await mock_kubernetes.patch_namespaced_pod_status(
        name=pods.items[0].metadata.name,
        namespace=namespace,
        body=[
            {
                "op": "replace",
                "path": "/status/phase",
                "value": PodPhase.SUCCEEDED.value,
            }
        ],
    )

    # Behind the scenes, the fileserver should notice that this pod completed,
    # delete it, and then clean up the other objects. It will delete the
    # GafaelfawrIngress and expect the Ingress to be automatically deleted,
    # which is true in real Kubernetes but not in the test suite so we need to
    # help it out by deleting the Ingress.
    await delete_ingress_for_user(mock_kubernetes, username, namespace)

    # Check that the fileserver user map is clear once we've given the server
    # a chance to notice it should delete things.
    await asyncio.sleep(0.1)
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == []

    # Check that the fileserver objects have been deleted
    objs = mock_kubernetes.get_namespace_objects_for_test(namespace)
    assert len(objs) == 2
    assert sorted(o.kind for o in objs) == ["Namespace", "ServiceAccount"]


@pytest.mark.asyncio
async def test_wait_for_ingress(
    *,
    client: AsyncClient,
    data: NubladoData,
    user: GafaelfawrTestUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    config = await configure(data, "fileserver", mock_kubernetes)
    assert config.fileserver.enabled
    username = user.username
    namespace = config.fileserver.namespace

    # No fileservers yet.
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == []

    # Start the fileserver, which will wait for the Ingress.
    task = asyncio.create_task(
        client.get("/files", headers=user.to_test_headers())
    )
    assert task.done() is False
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == []

    # Wait for longer than twice the reconcile interval to make sure that
    # reconciliation will not delete the pod creation in progress.
    delay = config.fileserver.reconcile_interval.total_seconds() * 2
    await asyncio.sleep(delay)

    # Create the Ingress.
    await create_working_ingress_for_user(mock_kubernetes, username, namespace)

    # Now the task will complete and we will have a fileserver.
    r = await task
    assert r.status_code == 200
    assert task.done() is True
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == [username]

    # Now remove the fileserver. Run this as a background task, wait for a
    # bit, and then delete the Ingress, which simulates what happens normally
    # in Kubernetes when the parent GafaelfawrIngress is deleted.
    delete_task = asyncio.create_task(
        client.delete(f"/nublado/fileserver/v1/users/{user.username}")
    )
    await asyncio.sleep(0.1)
    await delete_ingress_for_user(mock_kubernetes, username, namespace)
    r = await delete_task
    assert r.status_code == 204

    # Check that it's gone.
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == []


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_timeout_no_pod_start(
    *,
    client: AsyncClient,
    data: NubladoData,
    user: GafaelfawrTestUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    config = await configure(data, "fileserver", mock_kubernetes)
    assert config.fileserver.enabled
    username = user.username
    namespace = config.fileserver.namespace

    # Tell the Kubernetes mock to leave newly-created pods in pending status
    # rather than having them start automatically, simulating a fileserver pod
    # that never starts.
    mock_kubernetes.initial_pod_phase = "Pending"

    # Confirm there are no fileservers running at the start of the test.
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == []

    # Start a user fileserver. Pre-create an Ingress to match the
    # GafaelfawrIngress so that the creation succeeds.
    await create_working_ingress_for_user(mock_kubernetes, username, namespace)
    task = asyncio.create_task(
        client.get("/files", headers=user.to_test_headers())
    )

    # The start task will create the Job and then time out waiting for the Pod
    # to start, and then will attempt to clean up. We need to manually delete
    # the Ingress for it, since otherwise it will block waiting for the
    # ingress to disappear.
    await asyncio.sleep(0.1)
    await delete_ingress_for_user(mock_kubernetes, username, namespace)

    # Check that the start call raised a timeout error as expected.
    r = await task
    assert r.status_code == 500
    error = ErrorModel.model_validate(r.json())
    assert "File server creation timed out" in error.detail[0].msg

    # Check that the fileserver user map is still clear.
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == []


@pytest.mark.asyncio
async def test_timeout_no_ingress(
    *,
    client: AsyncClient,
    data: NubladoData,
    user: GafaelfawrTestUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    await configure(data, "fileserver", mock_kubernetes)

    # Confirm there are no fileservers running at the start of the test.
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == []

    # Start a user fileserver. Expect a timeout, because no Ingress was
    # created.
    r = await client.get("/files", headers=user.to_test_headers())
    assert r.status_code == 500
    error = ErrorModel.model_validate(r.json())
    assert "File server creation timed out" in error.detail[0].msg

    # Check that the fileserver user map is still clear.
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == []


@pytest.mark.asyncio
async def test_timeout_no_ingress_ip(
    *,
    client: AsyncClient,
    data: NubladoData,
    user: GafaelfawrTestUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    config = await configure(data, "fileserver", mock_kubernetes)
    assert config.fileserver.enabled
    namespace = config.fileserver.namespace

    # Confirm there are no fileservers running at the start of the test.
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == []

    # Start a user fileserver.
    task = asyncio.create_task(
        client.get("/files", headers=user.to_test_headers())
    )

    # Check there are no fileservers yet.
    assert task.done() is False
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == []

    # Create an Ingress that doesn't have an IP address. Expect a timeout when
    # the Ingress did not get an IP address within the timeout.
    await create_ingress_for_user(mock_kubernetes, user.username, namespace)
    r = await task
    assert r.status_code == 500
    error = ErrorModel.model_validate(r.json())
    assert "File server creation timed out" in error.detail[0].msg
    r = await client.get("/nublado/fileserver/v1/users")
    assert r.json() == []


@pytest.mark.asyncio
async def test_start_errors(
    *,
    client: AsyncClient,
    data: NubladoData,
    user: GafaelfawrTestUser,
    mock_kubernetes: MockKubernetesApi,
    mock_slack: MockSlackWebhook,
) -> None:
    config = await configure(data, "fileserver", mock_kubernetes)
    apis_to_fail = set()
    assert config.fileserver.enabled
    username = user.username
    namespace = config.fileserver.namespace

    def callback(method: str, *args: Any) -> None:
        if method in apis_to_fail:
            raise ApiException(status=400, reason="Something bad happened")

    mock_kubernetes.error_callback = callback

    # For each of the various Kubernetes calls that might fail, test that the
    # failure is caught, results in a reasonable error, and deletes the
    # remnants of the lab.
    possible_errors = [
        (
            "create_namespaced_custom_object",
            "GafaelfawrIngress",
            f"{namespace}/{username}-fs",
        ),
        (
            "create_namespaced_job",
            "Job",
            f"{namespace}/{username}-fs",
        ),
        (
            "create_namespaced_persistent_volume_claim",
            "PersistentVolumeClaim",
            f"{namespace}/{username}-fs-pvc-scratch",
        ),
        (
            "create_namespaced_service",
            "Service",
            f"{namespace}/{username}-fs",
        ),
    ]
    for api, kind, obj in possible_errors:
        apis_to_fail = {api}
        error_msg = f"Error creating object ({kind} {obj}, status 400)"
        await create_working_ingress_for_user(
            mock_kubernetes, username, namespace
        )
        task = asyncio.create_task(
            client.get("/files", headers=user.to_test_headers())
        )
        await asyncio.sleep(0.1)
        await delete_ingress_for_user(mock_kubernetes, username, namespace)
        r = await task
        assert r.status_code == 500
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
                                "text": f"*User*\n{username}",
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
        r = await client.get("/nublado/fileserver/v1/users")
        assert r.json() == []
        objs = mock_kubernetes.get_namespace_objects_for_test(namespace)
        assert [
            o for o in objs if o.kind not in ("Namespace", "ServiceAccount")
        ] == []
