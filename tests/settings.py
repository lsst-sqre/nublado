"""Produce a test object factory"""

from __future__ import annotations

import json
from base64 import b64encode
from typing import Any

from kubernetes_asyncio.client import (
    V1ContainerImage,
    V1Node,
    V1NodeStatus,
    V1ObjectMeta,
    V1Secret,
)

from jupyterlabcontroller.models.v1.lab import (
    LabSpecification,
    UserInfo,
    UserResources,
)
from jupyterlabcontroller.services.size import memory_string_to_int

# Factory to manufacture test objects


class TestObjectFactory:
    _filename = ""
    _canonicalized = False
    test_objects: dict[str, Any] = {}

    def initialize_from_file(self, filename: str) -> None:
        if filename and filename != self._filename:
            with open(filename) as f:
                self.test_objects = json.load(f)
                self._filename = filename
            self.canonicalize()

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
            for q in self.test_objects["resources"]:
                for i in ("limits", "requests"):
                    memfld = q[i]["memory"]
                    if type(memfld) is str:
                        q[i]["memory"] = memory_string_to_int(memfld)
        self._canonicalized = True

    @property
    def userinfos(self) -> dict[str, UserInfo]:
        return {
            t: UserInfo.parse_obj(d)
            for t, d in self.test_objects["user_info"].items()
        }

    @property
    def labspecs(self) -> list[LabSpecification]:
        if not self._canonicalized:
            self.canonicalize()
        return [
            LabSpecification.parse_obj(x)
            for x in self.test_objects["lab_specification"]
        ]

    @property
    def resources(self) -> list[UserResources]:
        if not self._canonicalized:
            self.canonicalize()
        return [
            UserResources.parse_obj(x) for x in self.test_objects["resources"]
        ]

    @property
    def nodecontents(self) -> list[V1Node]:
        nodes = []
        for name, data in self.test_objects["node_contents"].items():
            images = [
                V1ContainerImage(names=i["names"], size_bytes=i["sizeBytes"])
                for i in data
            ]
            node = V1Node(
                metadata=V1ObjectMeta(name=name),
                status=V1NodeStatus(images=images),
            )
            nodes.append(node)
        return nodes

    @property
    def repocontents(self) -> dict[str, str]:
        return self.test_objects["repo_contents"]

    @property
    def secrets(self) -> list[V1Secret]:
        secrets = []
        for name, data in self.test_objects["secrets"].items():
            encoded_data = {
                k: b64encode(v.encode()).decode() for k, v in data.items()
            }
            secret = V1Secret(
                metadata=V1ObjectMeta(name=name), data=encoded_data
            )
            if ".dockerconfigjson" in data:
                secret.type = "kubernetes.io/dockerconfigjson"
            secrets.append(secret)
        return secrets

    def get_user(self) -> tuple[str, UserInfo]:
        """Get user information and token for a user."""
        for token, user in self.userinfos.items():
            return token, user
        assert False, "No user information records configured"


test_object_factory = TestObjectFactory()
