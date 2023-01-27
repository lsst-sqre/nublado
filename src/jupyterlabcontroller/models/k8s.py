from copy import copy
from dataclasses import dataclass
from enum import auto
from typing import Dict, List, TypeAlias

from kubernetes_asyncio.client.models import V1ContainerImage

from .enums import NubladoEnum, NubladoTitleEnum


@dataclass
class ContainerImage:
    names: List[str]
    size_bytes: int

    @classmethod
    def from_v1_container_image(
        cls, img: V1ContainerImage
    ) -> "ContainerImage":
        return cls(names=copy(img.names), size_bytes=img.size_bytes)


@dataclass
class Secret:
    data: Dict[str, str]
    secret_type: str = "Opaque"


NodeContainers: TypeAlias = Dict[str, List[ContainerImage]]


class ObjectOperation(NubladoEnum):
    CREATION = auto()
    DELETION = auto()


class K8sPodPhase(NubladoTitleEnum):
    PENDING = auto()
    RUNNING = auto()
    SUCCEEDED = auto()
    FAILED = auto()
    UNKNOWN = auto()
