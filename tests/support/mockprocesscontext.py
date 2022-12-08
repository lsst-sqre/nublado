from typing import cast

from jupyterlabcontroller.config import Configuration
from jupyterlabcontroller.factory import ProcessContext

from ..settings import TestObjectFactory
from .mockdocker import MockDockerStorageClient
from .mockk8s import MockK8sStorageClient


class MockProcessContext(ProcessContext):
    """This simply replaces the storage clients with versions that mock their
    external calls."""

    @classmethod
    async def create(
        cls, config: Configuration, test_obj: TestObjectFactory
    ) -> "MockProcessContext":
        pc = await super().from_config(config)
        k8s_client = MockK8sStorageClient(test_obj=test_obj)
        docker_client = MockDockerStorageClient(test_obj=test_obj)
        pc.prepuller_executor.k8s_client.k8s_client = k8s_client
        pc.prepuller_executor.docker_client.docker_client = docker_client
        return cast("MockProcessContext", pc)
