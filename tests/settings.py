"""Produce a test object factory"""

from __future__ import annotations

import json
from copy import copy
from typing import Any, Dict, List

from jupyterlabcontroller.models.domain.prepuller import NodeContainers
from jupyterlabcontroller.models.domain.usermap import UserMap
from jupyterlabcontroller.models.k8s import ContainerImage
from jupyterlabcontroller.models.tag import RSPTag, TagMap
from jupyterlabcontroller.models.v1.lab import (
    LabSpecification,
    LabStatus,
    PodState,
    UserData,
    UserInfo,
    UserResources,
)
from jupyterlabcontroller.services.size import memory_string_to_int

# Factory to manufacture test objects


class TestObjectFactory:
    _filename = ""
    _canonicalized = False
    test_objects: Dict[str, Any] = dict()

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
            # Make node contents into NodeContainers
            new_nc: NodeContainers = dict()
            for node in self.test_objects["node_contents"]:
                nc = self.test_objects["node_contents"][node]
                clist: List[ContainerImage] = list()
                for img in nc:
                    clist.append(
                        ContainerImage(
                            names=copy(img["names"]),
                            size_bytes=img["sizeBytes"],
                        )
                    )
                new_nc[node] = clist
            self.test_objects["node_contents"] = new_nc
            # Make repo contents into TagMap
            bd: Dict[str, List[RSPTag]] = dict()
            ref = self.test_objects["user_options"][0]["image"].split(":")[0]
            tlm = self.test_objects["repo_contents"]["by_digest"]
            for digest in tlm:
                taglist = tlm[digest]
                if digest not in bd:
                    bd[digest] = list()
                for tag in taglist:
                    bd[digest].append(
                        RSPTag.from_tag(
                            tag=tag, digest=digest, image_ref=f"{ref}:{tag}"
                        )
                    )
            bt: Dict[str, RSPTag] = dict()
            tags = self.test_objects["repo_contents"]["by_tag"]
            for tag in tags:
                digest = self.test_objects["repo_contents"]["by_tag"][tag]
                bt[tag] = RSPTag.from_tag(
                    tag=tag, digest=digest, image_ref=f"{ref}:{tag}"
                )
            tag_map = TagMap(by_tag=bt, by_digest=bd)
            self.test_objects["repo_contents"] = tag_map
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
    def resources(self) -> List[UserResources]:
        if not self._canonicalized:
            self.canonicalize()
        return [
            UserResources.parse_obj(x) for x in self.test_objects["resources"]
        ]

    @property
    def userdatas(self) -> List[UserData]:
        userdatas: List[UserData] = list()
        labspecs = self.labspecs
        resources = self.resources
        userinfos = self.userinfos
        lab_statuses = [x for x in LabStatus]
        pod_states = [x for x in PodState]
        for idx, v in enumerate(userinfos):
            userdatas.append(
                UserData.from_components(
                    status=lab_statuses[idx % len(lab_statuses)],
                    pod=pod_states[(idx) % len(pod_states)],
                    user=v,
                    labspec=labspecs[idx % len(labspecs)],
                    resources=resources[idx % len(resources)],
                )
            )
        return userdatas

    @property
    def usermap(self) -> UserMap:
        usermap = UserMap()
        for v in self.userdatas:
            usermap.set(v.username, v)
        return usermap

    @property
    def nodecontents(self) -> NodeContainers:
        if not self._canonicalized:
            self.canonicalize()
        return self.test_objects["node_contents"]

    @property
    def repocontents(self) -> TagMap:
        if not self._canonicalized:
            self.canonicalize()
        return self.test_objects["repo_contents"]


test_object_factory = TestObjectFactory()
