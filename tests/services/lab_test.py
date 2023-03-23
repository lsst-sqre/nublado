import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from jupyterlabcontroller.factory import Factory
from jupyterlabcontroller.models.domain.docker import DockerReference

from ..settings import TestObjectFactory


def strip_none(model: dict[str, Any]) -> dict[str, Any]:
    """Strip `None` values from a serialized Kubernetes object.

    Comparing Kubernetes objects against serialized expected output is a bit
    of a pain, since Kubernetes objects often contain tons of optional
    parameters and the ``to_dict`` serialization includes every parameter.
    The naive result is therefore tedious to read or understand.

    This function works around this by taking a serialized Kubernetes object
    and dropping all of the parameters that are set to `None`. The ``to_dict``
    form of a Kubernetes object should be passed through it first before
    comparing to the expected output.

    Parmaters
    ---------
    model
        Kubernetes model serialized with ``to_dict``.

    Returns
    -------
    dict
        Cleaned-up model with `None` parameters removed.
    """
    result = {}
    for key, value in model.items():
        if value is None:
            continue
        if isinstance(value, dict):
            value = strip_none(value)
        elif isinstance(value, list):
            list_result = []
            for item in value:
                if isinstance(item, dict):
                    item = strip_none(item)
                list_result.append(item)
            value = list_result
        result[key] = value
    return result


@pytest.mark.asyncio
async def test_lab_manager(
    factory: Factory, obj_factory: TestObjectFactory
) -> None:
    token, user = obj_factory.get_user()
    lab = obj_factory.labspecs[0]
    lab_manager = factory.create_lab_manager()

    assert not lab_manager.check_for_user(user.username)
    await lab_manager.create_lab(user, token, lab)
    assert lab_manager.check_for_user(user.username)

    await lab_manager.delete_lab(user.username)
    assert not lab_manager.check_for_user(user.username)


@pytest.mark.asyncio
async def test_get_active_users(
    factory: Factory,
    obj_factory: TestObjectFactory,
) -> None:
    token, user = obj_factory.get_user()
    lab = obj_factory.labspecs[0]
    lab_manager = factory.create_lab_manager()

    assert await factory.user_map.running() == []

    await lab_manager.create_lab(user, token, lab)
    namespace = lab_manager.namespace_from_user(user)
    await lab_manager.await_pod_spawn(namespace, user.username)

    assert await factory.user_map.running() == [user.username]

    await lab_manager.delete_lab(user.username)

    # We have to let the background task run and complete the namespace
    # deletion.
    await asyncio.sleep(0.2)
    assert await factory.user_map.running() == []


@pytest.mark.asyncio
async def test_nss(
    factory: Factory, obj_factory: TestObjectFactory, std_result_dir: Path
) -> None:
    _, user = obj_factory.get_user()
    lab_manager = factory.create_lab_manager()
    nss = lab_manager.build_nss(user)
    for k in nss:
        dk = k.replace("/", "-")
        assert nss[k] == (std_result_dir / f"nss{dk}.txt").read_text()


@pytest.mark.asyncio
async def test_configmap(factory: Factory, std_result_dir: Path) -> None:
    lab_manager = factory.create_lab_manager()
    cm = lab_manager.build_file_configmap()
    for k in cm:
        dk = k.replace("/", "-")
        assert cm[k] == (std_result_dir / f"cm{dk}.txt").read_text()


@pytest.mark.asyncio
async def test_env(
    factory: Factory,
    obj_factory: TestObjectFactory,
    std_result_dir: Path,
) -> None:
    token, user = obj_factory.get_user()
    lab = obj_factory.labspecs[0]
    assert lab.options.image_list
    lab_manager = factory.create_lab_manager()

    reference = DockerReference.from_str(lab.options.image_list)
    image = await factory.image_service.image_for_reference(reference)
    env = lab_manager.build_env(user=user, lab=lab, image=image, token=token)
    with (std_result_dir / "env.json").open("r") as f:
        expected = json.load(f)
    assert env == expected


@pytest.mark.asyncio
async def test_pod_spec(
    factory: Factory, obj_factory: TestObjectFactory, std_result_dir: Path
) -> None:
    _, user = obj_factory.get_user()
    lab = obj_factory.labspecs[0]
    assert lab.options.image_list
    lab_manager = factory.create_lab_manager()
    size_manager = factory.create_size_manager()

    reference = DockerReference.from_str(lab.options.image_list)
    image = await factory.image_service.image_for_reference(reference)
    resources = size_manager.resources(lab.options.size)
    pod_spec = lab_manager.build_pod_spec(user, resources, image)
    with (std_result_dir / "pod.json").open("r") as f:
        expected = json.load(f)
    assert strip_none(pod_spec.to_dict()) == expected
