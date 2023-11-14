"""Tests for lab state management.

This is primarily tested through spawning and manipulating labs, mostly via
the tests of lab routes. The tests performed here are mostly about reconciling
state with Kubernetes.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from kubernetes_asyncio.client import ApiException
from safir.testing.kubernetes import MockKubernetesApi

from controller.config import Config
from controller.factory import Factory
from controller.models.domain.docker import DockerReference
from controller.models.domain.gafaelfawr import GafaelfawrUser
from controller.models.domain.kubernetes import PodPhase
from controller.models.v1.lab import (
    LabStatus,
    ResourceQuantity,
    UserInfo,
    UserLabState,
)

from ..support.data import (
    read_input_data,
    read_input_lab_specification_json,
    read_input_secrets_json,
)


async def create_lab(
    config: Config,
    factory: Factory,
    user: GafaelfawrUser,
    mock_kubernetes: MockKubernetesApi,
) -> UserLabState:
    """Create a lab for the default test user.

    This matches the behavior of the lab manager, but works behind its back so
    that it's not aware of the lab that was created. It is used to simulate
    labs that were already created when the lab controller started, and should
    be analyzed for reconciliation.

    Parameters
    ----------
    config
        Application configuration
    factory
        Component factory.
    user
        User whose lab is being created.
    mock_kubernetes
        Mock Kubernetes API.

    Returns
    -------
    UserLabState
        Expected state corresponding to the created lab.
    """
    assert user.quota
    assert user.quota.notebook
    lab = read_input_lab_specification_json("base", "lab-specification.json")
    size = config.lab.get_size_definition(lab.options.size)
    resources = size.to_lab_resources()
    await factory.image_service.refresh()
    assert lab.options.image_list
    reference = DockerReference.from_str(lab.options.image_list)
    image = await factory.image_service.image_for_reference(reference)
    lab.options.image_list = image.reference_with_digest
    lab_builder = factory.create_lab_builder()
    lab_storage = factory.create_lab_storage()

    # Create a lab outside of the normal creation flow by calling the builder
    # and storage methods to create the lab directly. It would be nice to use
    # the higher-level lab manager function, but it reports events to the lab
    # state manager, and we want the lab state manager to have no record of
    # anything to test reconciliation.
    #
    # Create this lab with an empty set of secret data, since it shouldn't
    # matter for what we're testing and saves some effort.
    objects = lab_builder.build_lab(
        user=user, lab=lab, image=image, secrets={}
    )
    await lab_storage.create(objects)

    phase = PodPhase(mock_kubernetes.initial_pod_phase)
    return UserLabState(
        env=lab.env,
        user=UserInfo.from_gafaelfawr(user),
        internal_url=(
            f"http://lab.userlabs-{user.username}:8888/nb/user/rachel/"
        ),
        options=lab.options,
        quota=ResourceQuantity(
            cpu=user.quota.notebook.cpu,
            memory=int(user.quota.notebook.memory * 1024 * 1024 * 1024),
        ),
        resources=resources,
        status=LabStatus.from_phase(phase),
    )


@pytest.mark.asyncio
async def test_reconcile(
    config: Config,
    factory: Factory,
    user: GafaelfawrUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    expected = await create_lab(config, factory, user, mock_kubernetes)

    # The lab state manager should think there are no labs.
    assert await factory.lab_manager.list_lab_users() == []

    # Now, start the background reconciliation thread. It should do an initial
    # reconciliation in the foreground, so when this returns, reconciliation
    # should be complete.
    await factory.start_background_services()

    # We should have picked up the manually-created pod and autodiscovered all
    # of its state.
    assert await factory.lab_manager.list_lab_users() == [user.username]
    state = await factory.lab_manager.get_lab_state(user.username)
    assert state
    assert state.model_dump() == expected.model_dump()


@pytest.mark.asyncio
async def test_reconcile_pending(
    config: Config,
    factory: Factory,
    user: GafaelfawrUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    mock_kubernetes.initial_pod_phase = PodPhase.PENDING.value
    expected = await create_lab(config, factory, user, mock_kubernetes)

    # The lab state manager shouldn't know about the pod to start with.
    assert await factory.lab_manager.list_lab_users() == []

    # Start the background processing. It should discover the pod on reconcile
    # and put it into pending status.
    await factory.start_background_services()
    await asyncio.sleep(0.1)
    state = await factory.lab_manager.get_lab_state(user.username)
    assert state
    assert state.status == LabStatus.PENDING
    assert state.model_dump() == expected.model_dump()

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
                "value": PodPhase.RUNNING.value,
            }
        ],
    )

    # Wait a little bit for the task to pick up the change and then check to
    # make sure the status updated.
    await asyncio.sleep(0.1)
    state = await factory.lab_manager.get_lab_state(user.username)
    assert state
    expected.status = LabStatus.RUNNING
    assert state.model_dump() == expected.model_dump()


@pytest.mark.asyncio
async def test_reconcile_succeeded(
    config: Config,
    factory: Factory,
    user: GafaelfawrUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    namespace = read_input_data("base", "metadata/namespace").strip()
    for secret in read_input_secrets_json("base", "secrets.json"):
        await mock_kubernetes.create_namespaced_secret(namespace, secret)
    mock_kubernetes.initial_pod_phase = PodPhase.SUCCEEDED.value
    await factory.start_background_services()

    # Create a lab through the controller. It should show up in a terminated
    # state.
    lab = read_input_lab_specification_json("base", "lab-specification.json")
    await factory.lab_manager.create_lab(user, lab)
    await asyncio.sleep(0.1)
    state = await factory.lab_manager.get_lab_state(user.username)
    assert state
    assert state.status == LabStatus.TERMINATED
    assert await mock_kubernetes.read_namespace(f"userlabs-{user.username}")

    # Now stop and start background services to force another run. The
    # reconciliation job should notice that the lab is in a terminated state
    # and delete it.
    await factory.stop_background_services()
    await factory.start_background_services()
    with pytest.raises(ApiException) as excinfo:
        await mock_kubernetes.read_namespace(f"userlabs-{user.username}")
    assert excinfo.value.status == 404


@pytest.mark.asyncio
async def test_spawn_timeout(
    config: Config,
    factory: Factory,
    user: GafaelfawrUser,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    namespace = read_input_data("base", "metadata/namespace").strip()
    for secret in read_input_secrets_json("base", "secrets.json"):
        await mock_kubernetes.create_namespaced_secret(namespace, secret)
    mock_kubernetes.initial_pod_phase = PodPhase.PENDING.value
    config.lab.spawn_timeout = timedelta(seconds=1)
    lab = read_input_lab_specification_json("base", "lab-specification.json")
    await factory.start_background_services()

    # Start the lab creation.
    await factory.lab_manager.create_lab(user, lab)
    await asyncio.sleep(0.1)
    state = await factory.lab_manager.get_lab_state(user.username)
    assert state
    assert state.status == LabStatus.PENDING

    # Wait for half the timeout and the status should still be pending.
    await asyncio.sleep(0.5)
    state = await factory.lab_manager.get_lab_state(user.username)
    assert state
    assert state.status == LabStatus.PENDING

    # Wait for the timeout. The lab creation should have failed with an
    # appropriate event.
    await asyncio.sleep(0.5)
    state = await factory.lab_manager.get_lab_state(user.username)
    assert state
    assert state.status == LabStatus.FAILED
    events = [
        e async for e in factory.lab_manager.events_for_user(user.username)
    ]
    assert events[-1].data
    assert "Lab spawn timed out after" in events[-1].data
