import json
from dataclasses import asdict
from pathlib import Path

import pytest
from kubernetes_asyncio.client import (
    V1ConfigMapEnvSource,
    V1ConfigMapVolumeSource,
    V1Container,
    V1ContainerPort,
    V1DownwardAPIVolumeFile,
    V1DownwardAPIVolumeSource,
    V1EmptyDirVolumeSource,
    V1EnvFromSource,
    V1EnvVar,
    V1EnvVarSource,
    V1KeyToPath,
    V1NFSVolumeSource,
    V1ObjectFieldSelector,
    V1PodSecurityContext,
    V1PodSpec,
    V1ResourceFieldSelector,
    V1SecretVolumeSource,
    V1SecurityContext,
    V1Volume,
    V1VolumeMount,
)

from jupyterlabcontroller.factory import Factory

from ..settings import TestObjectFactory


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
    namespace = lab_manager.namespace_from_user(user)
    await lab_manager.await_ns_deletion(namespace, user.username)
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
    lab_manager = factory.create_lab_manager()

    env = lab_manager.build_env(user, lab, token)
    with (std_result_dir / "env.json").open("r") as f:
        expected = json.load(f)
    assert env == expected


@pytest.mark.asyncio
async def test_build_volumes(
    factory: Factory,
    obj_factory: TestObjectFactory,
    std_result_dir: Path,
) -> None:
    _, user = obj_factory.get_user()
    lab_manager = factory.create_lab_manager()
    volumes = lab_manager.build_volumes(user.username)

    # Unfortunately, the serialization of Kubernetes API objects is huge (it
    # contains every possible field) and potentially unstable if Kubernetes
    # adds new mount types. Just inline the comparison as Python instead.
    assert [asdict(v) for v in volumes] == [
        {
            "volume": V1Volume(
                name="home",
                nfs=V1NFSVolumeSource(
                    path="/share1/home",
                    read_only=False,
                    server="10.13.105.122",
                ),
            ),
            "volume_mount": V1VolumeMount(
                mount_path="/home", name="home", read_only=False
            ),
        },
        {
            "volume": V1Volume(
                name="project",
                nfs=V1NFSVolumeSource(
                    path="/share1/project",
                    read_only=True,
                    server="10.13.105.122",
                ),
            ),
            "volume_mount": V1VolumeMount(
                mount_path="/project", name="project", read_only=True
            ),
        },
        {
            "volume": V1Volume(
                name="scratch",
                nfs=V1NFSVolumeSource(
                    path="/share1/scratch",
                    read_only=False,
                    server="10.13.105.122",
                ),
            ),
            "volume_mount": V1VolumeMount(
                mount_path="/scratch", name="scratch", read_only=False
            ),
        },
        {
            "volume": V1Volume(
                name="nss-rachel-passwd",
                config_map=V1ConfigMapVolumeSource(
                    name="nb-rachel-nss",
                    items=[
                        V1KeyToPath(
                            mode=0o644, key="_._etc_._passwd", path="passwd"
                        )
                    ],
                ),
            ),
            "volume_mount": V1VolumeMount(
                mount_path="/etc/passwd",
                name="nss-rachel-passwd",
                read_only=True,
                sub_path="passwd",
            ),
        },
        {
            "volume": V1Volume(
                name="nss-rachel-group",
                config_map=V1ConfigMapVolumeSource(
                    name="nb-rachel-nss",
                    items=[
                        V1KeyToPath(
                            mode=0o644, key="_._etc_._group", path="group"
                        )
                    ],
                ),
            ),
            "volume_mount": V1VolumeMount(
                mount_path="/etc/group",
                name="nss-rachel-group",
                read_only=True,
                sub_path="group",
            ),
        },
        {
            "volume": V1Volume(
                name="nss-rachel-lsst-dask-yml",
                config_map=V1ConfigMapVolumeSource(
                    name="nb-rachel-configmap",
                    items=[
                        V1KeyToPath(
                            mode=0o644,
                            key=(
                                "_._opt_._lsst_._software_._jupyterlab"
                                "_._lsst_dask.yml"
                            ),
                            path="lsst_dask.yml",
                        )
                    ],
                ),
            ),
            "volume_mount": V1VolumeMount(
                mount_path="/opt/lsst/software/jupyterlab/lsst_dask.yml",
                name="nss-rachel-lsst-dask-yml",
                read_only=True,
                sub_path="lsst_dask.yml",
            ),
        },
        {
            "volume": V1Volume(
                name="nss-rachel-panda",
                config_map=V1ConfigMapVolumeSource(
                    name="nb-rachel-configmap",
                    items=[
                        V1KeyToPath(
                            mode=0o644,
                            key=(
                                "_._opt_._lsst_._software_._jupyterlab"
                                "_._panda"
                            ),
                            path="panda",
                        )
                    ],
                ),
            ),
            "volume_mount": V1VolumeMount(
                mount_path="/opt/lsst/software/jupyterlab/panda",
                name="nss-rachel-panda",
                read_only=True,
                sub_path="panda",
            ),
        },
        {
            "volume": V1Volume(
                name="nb-rachel-secrets",
                secret=V1SecretVolumeSource(secret_name="nb-rachel"),
            ),
            "volume_mount": V1VolumeMount(
                mount_path="/opt/lsst/software/jupyterlab/secrets",
                name="nb-rachel-secrets",
                read_only=True,
            ),
        },
        {
            "volume": V1Volume(
                name="nb-rachel-env",
                config_map=V1ConfigMapVolumeSource(
                    name="nb-rachel-env",
                ),
            ),
            "volume_mount": V1VolumeMount(
                mount_path="/opt/lsst/software/jupyterlab/environment",
                name="nb-rachel-env",
                read_only=False,
            ),
        },
        {
            "volume": V1Volume(
                empty_dir=V1EmptyDirVolumeSource(),
                name="tmp",
            ),
            "volume_mount": V1VolumeMount(
                mount_path="/tmp",
                read_only=False,
                name="tmp",
            ),
        },
        {
            "volume": V1Volume(
                name="nb-rachel-runtime",
                downward_api=V1DownwardAPIVolumeSource(
                    items=[
                        V1DownwardAPIVolumeFile(
                            resource_field_ref=V1ResourceFieldSelector(
                                container_name="notebook",
                                resource="limits.cpu",
                            ),
                            path="limits_cpu",
                        ),
                        V1DownwardAPIVolumeFile(
                            resource_field_ref=V1ResourceFieldSelector(
                                container_name="notebook",
                                resource="requests.cpu",
                            ),
                            path="requests_cpu",
                        ),
                        V1DownwardAPIVolumeFile(
                            resource_field_ref=V1ResourceFieldSelector(
                                container_name="notebook",
                                resource="limits.memory",
                            ),
                            path="limits_memory",
                        ),
                        V1DownwardAPIVolumeFile(
                            resource_field_ref=V1ResourceFieldSelector(
                                container_name="notebook",
                                resource="requests.memory",
                            ),
                            path="requests_memory",
                        ),
                    ],
                ),
            ),
            "volume_mount": V1VolumeMount(
                mount_path="/opt/lsst/software/jupyterlab/runtime",
                name="nb-rachel-runtime",
                read_only=True,
            ),
        },
    ]


@pytest.mark.asyncio
async def test_pod_spec(
    factory: Factory, obj_factory: TestObjectFactory, std_result_dir: Path
) -> None:
    _, user = obj_factory.get_user()
    lab = obj_factory.labspecs[0]
    lab_manager = factory.create_lab_manager()
    volumes = lab_manager.build_volumes(user.username)

    assert (
        lab_manager.build_pod_spec(user, lab).to_dict()
        == V1PodSpec(
            containers=[
                V1Container(
                    name="notebook",
                    args=["/opt/lsst/software/jupyterlab/runlab.sh"],
                    env=[
                        V1EnvVar(
                            name="K8S_NODE_NAME",
                            value_from=V1EnvVarSource(
                                field_ref=V1ObjectFieldSelector(
                                    field_path="spec.nodeName"
                                )
                            ),
                        ),
                    ],
                    env_from=[
                        V1EnvFromSource(
                            config_map_ref=V1ConfigMapEnvSource(
                                name="nb-rachel-env"
                            )
                        ),
                    ],
                    image=(
                        "lighthouse.ceres/library/sketchbook:latest_daily"
                        "@sha256:1234"
                    ),
                    image_pull_policy="Always",
                    ports=[
                        V1ContainerPort(
                            container_port=8888,
                            name="jupyterlab",
                        ),
                    ],
                    security_context=V1SecurityContext(
                        run_as_non_root=True,
                        run_as_user=1101,
                    ),
                    volume_mounts=[v.volume_mount for v in volumes],
                    working_dir="/home/rachel",
                )
            ],
            init_containers=[],
            restart_policy="OnFailure",
            security_context=V1PodSecurityContext(
                run_as_non_root=True,
                fs_group=1101,
                supplemental_groups=[1101, 2028, 2001, 2021],
            ),
            volumes=[v.volume for v in volumes],
        ).to_dict()
    )
