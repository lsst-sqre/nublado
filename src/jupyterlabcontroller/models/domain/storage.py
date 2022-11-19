from dataclasses import dataclass

from ...storage.docker import DockerStorageClient
from ...storage.k8s import K8sStorageClient


@dataclass
class StorageClientBundle:
    k8s_client: K8sStorageClient
    docker_client: DockerStorageClient
