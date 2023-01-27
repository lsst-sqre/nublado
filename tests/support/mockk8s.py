from typing import Dict

from kubernetes_asyncio.client.models import V1PodSpec, V1Secret

from jupyterlabcontroller.models.v1.lab import UserData
from jupyterlabcontroller.storage.k8s import (
    K8sStorageClient,
    NodeContainers,
    UserResourceQuantum,
)

from ..settings import TestObjectFactory


class MockK8sStorageClient(K8sStorageClient):
    def __init__(self, test_obj: TestObjectFactory) -> None:
        self._test_obj = test_obj

    async def create_user_namespace(self, ns_name: str) -> None:
        pass

    async def create_secret(
        self,
        name: str,
        namespace: str,
        data: Dict[str, str],
        secret_type: str = "Opaque",
        immutable: bool = False,
    ) -> None:
        pass

    async def read_secret(self, name: str, namespace: str) -> V1Secret:
        return V1Secret(data={})

    async def create_configmap(
        self,
        name: str,
        namespace: str,
        data: Dict[str, str],
        immutable: bool = True,
    ) -> None:
        pass

    async def create_network_policy(self, name: str, namespace: str) -> None:
        pass

    async def create_quota(
        self,
        name: str,
        namespace: str,
        quota: UserResourceQuantum,
    ) -> None:
        pass

    async def create_pod(
        self,
        name: str,
        namespace: str,
        pod: V1PodSpec,
        pull_secret: bool = False,
        labels: Dict[str, str] = dict(),
    ) -> None:
        pass

    async def delete_namespace(
        self,
        namespace: str,
    ) -> None:
        pass

    async def get_image_data(self) -> NodeContainers:
        return self._test_obj.nodecontents

    async def wait_for_pod_creation(
        self, podname: str, namespace: str, interval: float = 0.2
    ) -> None:
        pass

    async def wait_for_namespace_deletion(
        self, namespace: str, interval: float = 0.2
    ) -> None:
        pass

    async def get_observed_user_state(
        self, manager_namespace: str
    ) -> Dict[str, UserData]:
        mtd: Dict[str, UserData] = dict()
        return mtd
