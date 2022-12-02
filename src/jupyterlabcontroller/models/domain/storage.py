from dataclasses import dataclass
from typing import List, Optional

from ...models.v1.lab import UserInfo
from ...storage.docker import DockerStorageClient
from ...storage.gafaelfawr import GafaelfawrStorageClient
from ...storage.k8s import K8sStorageClient


@dataclass
class StorageClientBundle:
    k8s_client: K8sStorageClient
    docker_client: DockerStorageClient
    gafaelfawr_client: GafaelfawrStorageClient


@dataclass
class GafaelfawrCache:
    user: Optional[UserInfo] = None
    scopes: Optional[List[str]] = None
