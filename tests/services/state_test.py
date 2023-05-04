"""Tests for lab state management.

This is primarily tested through spawning and manipulating labs, mostly via
the tests of lab routes. The tests performed here are mostly about reconciling
state with Kubernetes.
"""

from __future__ import annotations

import pytest
from safir.testing.kubernetes import MockKubernetesApi

from jupyterlabcontroller.config import Config
from jupyterlabcontroller.factory import Factory
from jupyterlabcontroller.models.domain.docker import DockerReference
from jupyterlabcontroller.models.v1.lab import LabStatus, PodState

from ..settings import TestObjectFactory


@pytest.mark.asyncio
async def test_reconcile(
    config: Config,
    factory: Factory,
    obj_factory: TestObjectFactory,
    mock_kubernetes: MockKubernetesApi,
) -> None:
    for secret in obj_factory.secrets:
        await mock_kubernetes.create_namespaced_secret(
            config.lab.namespace_prefix, secret
        )
    token, user = obj_factory.get_user()
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
    await lab_manager.create_secrets(user, token)
    await lab_manager.create_nss(user)
    await lab_manager.create_file_configmap(user)
    await lab_manager.create_env(user=user, lab=lab, image=image, token=token)
    await lab_manager.create_network_policy(user)
    await lab_manager.create_quota(user)
    await lab_manager.create_lab_service(user)
    await lab_manager.create_user_pod(user, resources, image)

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
    assert state.dict() == {
        "env": lab.env,
        "gid": user.gid,
        "groups": user.dict()["groups"],
        "internal_url": (
            f"http://lab.userlabs-{user.username}:8888/nb/user/rachel/"
        ),
        "name": user.name,
        "options": lab.options.dict(),
        "pod": PodState.PRESENT,
        "quota": {"api": {}, "notebook": {"cpu": 9.0, "memory": 27.0}},
        "resources": resources.dict(),
        "status": LabStatus.RUNNING,
        "uid": user.uid,
        "username": user.username,
    }
    status = await factory.lab_state.get_lab_status(user.username)
    assert status == LabStatus.RUNNING
