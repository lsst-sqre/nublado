"""Set the configuration, and build factories for producing test
dependencies and objects."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import structlog
from aiojobs import Scheduler
from httpx import AsyncClient
from kubernetes_asyncio.client import ApiClient
from kubernetes_asyncio.client.models import V1ContainerImage
from structlog.stdlib import BoundLogger

from jupyterlabcontroller.dependencies.config import configuration_dependency
from jupyterlabcontroller.models.v1.consts import (
    DOCKER_SECRETS_PATH,
    lab_statuses,
    pod_states,
)
from jupyterlabcontroller.models.v1.domain.config import Config
from jupyterlabcontroller.models.v1.domain.labs import LabMap
from jupyterlabcontroller.models.v1.domain.prepuller import NodeContainers
from jupyterlabcontroller.models.v1.external.event import EventMap
from jupyterlabcontroller.models.v1.external.userdata import (
    LabSpecification,
    UserData,
    UserInfo,
    UserQuota,
)
from jupyterlabcontroller.storage.docker import DockerClient
from jupyterlabcontroller.storage.events import EventManager
from jupyterlabcontroller.storage.prepuller import PrepullerClient
from jupyterlabcontroller.utils import memory_string_to_int


def config_config(config_path: str) -> Config:
    """Change the test application configuration.

    Parameters
    ----------
    config_path
      Path to a directory that contains a configuration file
      ``configuration.yaml``, which is the YAML that would usually be
      mounted into the container at ``/etc/nublado/config.yaml``.
    """
    configuration_dependency.set_configuration_path(
        f"{config_path}/config.yaml"
    )
    return configuration_dependency.config()


# Factory to manufacture FastAPI dependency equivalent objects (but only
# the ones that are not really request-dependent)
@dataclass
class TestDependencyFactory:
    config: Config
    httpx_client: AsyncClient
    logger: BoundLogger
    docker_client: DockerClient
    event_manager: EventManager
    k8s_client: ApiClient
    prepuller_client: PrepullerClient
    scheduler: Scheduler

    @classmethod
    def initialize(
        cls, config: Config, httpx_client: AsyncClient
    ) -> TestDependencyFactory:

        logger = structlog.get_logger(name=config.safir.logger_name)

        # Docker Client
        modified_cfg_dir: Optional[str] = os.getenv(
            "JUPYTERLAB_CONTROLLER_CONFIGURATION_DIR"
        )
        secrets_path: str = DOCKER_SECRETS_PATH
        if modified_cfg_dir:
            secrets_path = "{modified_cfg_dir}/docker_config.json"
        docker_client = DockerClient(
            logger=logger,
            config=config,
            http_client=httpx_client,
            secrets_path=secrets_path,
        )

        # Event Manager
        em: EventMap = {}
        event_manager = EventManager(logger=logger, events=em)

        # K8s client
        k8s_client = ApiClient()

        # Prepuller client
        prepuller_client = PrepullerClient(
            logger=logger,
            config=config,
            docker_client=docker_client,
            api=k8s_client,
        )

        # Scheduler
        scheduler = Scheduler(close_timeout=config.kubernetes.request_timeout)
        return cls(
            config=config,
            httpx_client=httpx_client,
            logger=logger,
            docker_client=docker_client,
            event_manager=event_manager,
            k8s_client=k8s_client,
            prepuller_client=prepuller_client,
            scheduler=scheduler,
        )


# Factory to manufacture test objects


class TestObjectFactory:
    _canonicalized: bool = False
    test_objects: Dict[str, Any] = {
        "user_info": [
            {
                "username": "rachel",
                "name": "Rachel (?)",
                "uid": 1101,
                "gid": 1101,
                "groups": [
                    {"name": "rachel", "id": 1101},
                    {"name": "lunatics", "id": 2028},
                    {"name": "mechanics", "id": 2001},
                    {"name": "storytellers", "id": 2021},
                ],
            },
            {
                "username": "wrench",
                "name": "Wrench",
                "uid": 1102,
                "gid": 1102,
                "groups": [
                    {"name": "wrench", "id": 1102},
                    {"name": "jovians", "id": 2010},
                    {"name": "mechanics", "id": 2001},
                ],
            },
            {
                "username": "violet",
                "name": "Violet",
                "uid": 1103,
                "gid": 1103,
                "groups": [
                    {"name": "violet", "id": 1103},
                    {"name": "saturnians", "id": 2011},
                    {"name": "pirates", "id": 2002},
                ],
            },
            {
                "username": "ribbon",
                "name": "Ribbon",
                "uid": 1104,
                "gid": 1104,
                "groups": [
                    {"name": "ribbon", "id": 1104},
                    {"name": "ferrymen", "id": 2023},
                    {"name": "ninjas", "id": 2003},
                ],
            },
        ],
        "quotas": [
            {
                "limits": {
                    "cpu": 4.0,
                    "memory": "12Gi",
                },
                "requests": {"cpu": 1.0, "memory": "3Gi"},
            },
        ],
        "env": [
            {
                "HOME": "/home/ceres",
                "SHELL": "/bin/bash",
            },
        ],
        "user_options": [
            {
                "image": "lighthouse.ceres/library/sketchbook:latest_daily",
                "size": "small",
            },
        ],
        "lab_specification": [],
        "node_contents": {
            "node1": [
                {
                    "names": [
                        "library/sketchbook:latest_daily",
                        "library/sketchbook:d_2077_10_23",
                        "library/sketchbook@sha256:1234",
                    ],
                    "sizeBytes": 69105,
                },
                {
                    "names": [
                        "library/sketchbook:latest_weekly",
                        "library/sketchbook:w_2077_43",
                        "library/sketchbook:recommended",
                        "library/sketchbook@sha256:5678",
                    ],
                    "sizeBytes": 65537,
                },
            ],
            "node2": [
                {
                    "names": [
                        "library/sketchbook:latest_weekly",
                        "library/sketchbook:w_2077_43",
                        "library/sketchbook:recommended",
                        "library/sketchbook@sha256:5678",
                    ],
                    "sizeBytes": 65537,
                },
            ],
        },
    }

    def canonicalize(self) -> None:
        if self._canonicalized:
            return
        for idx, x in enumerate(self.test_objects["user_options"]):
            # Glue options and envs into lab specifications
            self.test_objects["lab_specification"].append(
                {
                    "options": x,
                    "env": self.test_objects["env"][
                        idx % len(self.test_objects["env"])
                    ],
                }
            )
            # Set memory to bytes rather than text (e.g. "3KiB" -> 3072)
            for q in self.test_objects["quotas"]:
                for i in ("limits", "requests"):
                    memfld = q[i]["memory"]
                    if type(memfld) is str:
                        q[i]["memory"] = memory_string_to_int(memfld)
            # Make node contents into V1ContainerImage
            for node in self.test_objects["node_contents"]:
                clist: List[V1ContainerImage] = []
                for img in self.test_objects["node_contents"][node]:
                    clist.append(V1ContainerImage(img))
                self.test_objects["node_contents"][node] = clist

        self._canonicalized = True

    @property
    def userinfos(self) -> List[UserInfo]:
        return [UserInfo.parse_obj(x) for x in self.test_objects["user_info"]]

    @property
    def labspecs(self) -> List[LabSpecification]:
        if not self._canonicalized:
            self.canonicalize()
        return [
            LabSpecification.parse_obj(x)
            for x in self.test_objects["lab_specification"]
        ]

    @property
    def quotas(self) -> List[UserQuota]:
        if not self._canonicalized:
            self.canonicalize()
        return [UserQuota.parse_obj(x) for x in self.test_objects["quotas"]]

    @property
    def userdatas(self) -> List[UserData]:
        userdatas: List[UserData] = []
        labspecs = self.labspecs
        quotas = self.quotas
        userinfos = self.userinfos
        for idx, v in enumerate(userinfos):
            userdatas.append(
                UserData.from_components(
                    status=lab_statuses[idx % len(lab_statuses)],
                    pod=pod_states[(idx) % len(pod_states)],
                    user=v,
                    labspec=labspecs[idx % len(labspecs)],
                    quotas=quotas[idx % len(quotas)],
                )
            )
        return userdatas

    @property
    def labmap(self) -> LabMap:
        labmap: LabMap = {}
        for v in self.userdatas:
            n = v.username
            labmap[n] = v
        return labmap

    @property
    def nodecontents(self) -> NodeContainers:
        retval: NodeContainers = {}
        for node in self.test_objects["node_contents"]:
            clist: List[V1ContainerImage] = []
            for img in self.test_objects["node_contents"][node]:
                clist.append(V1ContainerImage(img))
            retval[node] = clist
        return retval


test_object_factory = TestObjectFactory()
