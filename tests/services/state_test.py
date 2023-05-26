"""Tests for lab state management.

This is primarily tested through spawning and manipulating labs, mostly via
the tests of lab routes. The tests performed here are mostly about reconciling
state with Kubernetes.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from safir.testing.kubernetes import MockKubernetesApi

from jupyterlabcontroller.config import Config
from jupyterlabcontroller.factory import Factory
from jupyterlabcontroller.models.domain.docker import DockerReference
from jupyterlabcontroller.models.domain.gafaelfawr import GafaelfawrUser
from jupyterlabcontroller.models.domain.kubernetes import KubernetesPodPhase
from jupyterlabcontroller.models.v1.lab import (
    LabStatus,
    PodState,
    ResourceQuantity,
    UserInfo,
    UserLabState,
)

from ..settings import TestObjectFactory


async def create_lab(
    config: Config,
    factory: Factory,
    obj_factory: TestObjectFactory,
    mock_kubernetes: MockKubernetesApi,
) -> UserLabState:
    """Create a lab for the default test user.

    This matches the behavior of the lab manager, but works below the level of
    the lab manager and the lab state manager. It is used to simulate labs
    that were already created when the lab controller started, and should be
    analyzed for reconciliation.

    Parameters
    ----------
    config
        Application configuration
    factory
        Component factory.
    obj_factory
        Test data source.
    mock_kubernetes
        Mock Kubernetes API.

    Returns
    -------
    UserLabState
        Expected state corresponding to the created lab.
    """
    for secret in obj_factory.secrets:
        await mock_kubernetes.create_namespaced_secret(
            config.lab.namespace_prefix, secret
        )
    token, user = obj_factory.get_user()
    user = GafaelfawrUser(token=token, **user.dict())
    assert user.quota
    assert user.quota.notebook
    lab = obj_factory.labspecs[0]
    lab_manager = factory.create_lab_manager()
    size_manager = factory.create_size_manager()
    resources = size_manager.resources(lab.options.size)
    await factory.image_service.refresh()
    assert lab.options.image_list
    reference = DockerReference.from_str(lab.options.image_list)
    image = await factory.image_service.image_for_reference(reference)
    lab.options.image_list = image.reference_with_digest

    # Create a lab outside of the normal creation flow by calling the internal
    # methods to create the lab directly. It would be nice to use the
    # higher-level lab manager function, but it reports events to the lab
    # state manager, and we want the lab state manager to have no record of
    # anything to test reconciliation.
    await lab_manager.create_namespace(user)
    await lab_manager.create_secrets(user)
    await lab_manager.create_nss(user)
    await lab_manager.create_file_configmap(user)
    await lab_manager.create_env(user, lab, image)
    await lab_manager.create_network_policy(user)
    await lab_manager.create_quota(user)
    await lab_manager.create_lab_service(user)
    await lab_manager.create_user_pod(user, resources, image)

    return UserLabState(
        env=lab.env,
        user=UserInfo.from_gafaelfawr(user),
        internal_url=(
            f"http://lab.userlabs-{user.username}:8888/nb/user/rachel/"
        ),
        options=lab.options,
        pod=PodState.PRESENT,
        quota=ResourceQuantity(
            cpu=user.quota.notebook.cpu,
            memory=int(user.quota.notebook.memory * 1024 * 1024 * 1024),
        ),
        resources=resources,
        status=LabStatus.from_phase(mock_kubernetes.initial_pod_phase),
    )


@pytest.mark.asyncio
async def test_reconcile(
    config: Config,
    factory: Factory,
    obj_factory: TestObjectFactory,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    expected = await create_lab(config, factory, obj_factory, mock_kubernetes)
    _, user = obj_factory.get_user()

    # The lab state manager should think there are no labs.
    assert await factory.lab_state.list_lab_users() == []

    # Now, start the background reconciliation thread. It should do an initial
    # reconciliation in the foreground, so when this returns, reconciliation
    # should be complete.
    await factory.start_background_services()

    # We should have picked up the manually-created pod and autodiscovered all
    # of its state.
    assert await factory.lab_state.list_lab_users() == [user.username]
    state = await factory.lab_state.get_lab_state(user.username)
    assert state.dict() == expected.dict()
    status = await factory.lab_state.get_lab_status(user.username)
    assert status == LabStatus.RUNNING


@pytest.mark.asyncio
async def test_reconcile_pending(
    config: Config,
    factory: Factory,
    obj_factory: TestObjectFactory,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    mock_kubernetes.initial_pod_phase = KubernetesPodPhase.PENDING.value
    expected = await create_lab(config, factory, obj_factory, mock_kubernetes)
    _, user = obj_factory.get_user()

    # The lab state manager shouldn't know about the pod to start with.
    assert await factory.lab_state.list_lab_users() == []

    # Start the background processing. It should discover the pod on reconcile
    # and put it into pending status.
    await factory.start_background_services()
    await asyncio.sleep(0.1)
    state = await factory.lab_state.get_lab_state(user.username)
    assert state.status == LabStatus.PENDING
    assert state.dict() == expected.dict()

    # Change the pod status and post an event. This should cause the
    # background monitoring task to pick up the change and convert the pod
    # status to running.
    await mock_kubernetes.patch_namespaced_pod_status(
        f"{user.username}-nb",
        f"userlabs-{user.username}",
        [
            {
                "op": "replace",
                "path": "/status/phase",
                "value": KubernetesPodPhase.RUNNING.value,
            }
        ],
    )

    # Wait a little bit for the task to pick up the change and then check to
    # make sure the status updated.
    await asyncio.sleep(0.1)
    state = await factory.lab_state.get_lab_state(user.username)
    expected.status = LabStatus.RUNNING
    assert state.dict() == expected.dict()


@pytest.mark.asyncio
async def test_spawn_timeout(
    config: Config,
    factory: Factory,
    obj_factory: TestObjectFactory,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    for secret in obj_factory.secrets:
        await mock_kubernetes.create_namespaced_secret(
            config.lab.namespace_prefix, secret
        )
    mock_kubernetes.initial_pod_phase = KubernetesPodPhase.PENDING.value
    config.lab.spawn_timeout = timedelta(seconds=1)
    token, user = obj_factory.get_user()
    user = GafaelfawrUser(token=token, **user.dict())
    lab = obj_factory.labspecs[0]
    lab_manager = factory.create_lab_manager()
    await factory.start_background_services()

    # Start the lab creation.
    await lab_manager.create_lab(user, lab)
    await asyncio.sleep(0.1)
    status = await factory.lab_state.get_lab_status(user.username)
    assert status == LabStatus.PENDING

    # Wait for half the timeout and the status should still be pending.
    await asyncio.sleep(0.5)
    status = await factory.lab_state.get_lab_status(user.username)
    assert status == LabStatus.PENDING

    # Wait for the timeout. The lab creation should have failed with an
    # appropriate event.
    await asyncio.sleep(0.5)
    status = await factory.lab_state.get_lab_status(user.username)
    assert status == LabStatus.FAILED
    events = []
    async for event in factory.lab_state.events_for_user(user.username):
        events.append(event)
    assert events[-2].data and events[-1].data
    assert "Lab creation timed out after" in events[-2].data
    assert "Lab creation failed" in events[-1].data
