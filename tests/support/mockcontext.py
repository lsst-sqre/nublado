from dataclasses import dataclass

from jupyterlabcontroller.models.context import Context
from jupyterlabcontroller.models.storage.docker import DockerStorageClient
from jupyterlabcontroller.models.storage.gafaelfawr import (
    GafaelfawrStorageClient,
)
from jupyterlabcontroller.models.storage.k8s import K8sStorageClient

from ..conftest import TestObjectFactory
from .mockdocker import MockDockerStorageClient
from .mockgafaelfawr import MockGafaelfawrStorageClient
from .mockk8s import MockK8sStorageClient


@dataclass
class MockContext(Context):
    test_obj: TestObjectFactory

    @property
    def gafaelfawr_client(self) -> GafaelfawrStorageClient:
        return MockGafaelfawrStorageClient(test_obj=self.test_obj)

    @property
    def docker_client(self) -> DockerStorageClient:
        return MockDockerStorageClient(test_obj=self.test_obj)

    @property
    def k8s_client(self) -> K8sStorageClient:
        return MockK8sStorageClient(test_obj=self.test_obj)
