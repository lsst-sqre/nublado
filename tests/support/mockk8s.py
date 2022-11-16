from typing import Dict

from jupyterlabcontroller.storage.k8s import (
    K8sStorageClient,
    NetworkPolicySpec,
    NodeContainers,
    PodSpec,
    Secret,
    UserResourceQuantum,
)

from ..settings import TestObjectFactory


class MockK8sStorageClient(K8sStorageClient):
    def __init__(self, test_obj: TestObjectFactory) -> None:
        self._test_obj = test_obj

    async def create_namespace(self, ns_name: str) -> None:
        pass

    async def create_secret(
        self,
        name: str,
        namespace: str,
        data: Dict[str, str],
        immutable: bool = False,
    ) -> None:
        pass

    async def read_secret(self, name: str, namespace: str) -> Secret:
        return Secret(data={})

    async def create_configmap(
        self,
        name: str,
        namespace: str,
        data: Dict[str, str],
        immutable: bool = True,
    ) -> None:
        pass

    async def create_network_policy(
        self, name: str, namespace: str, spec: NetworkPolicySpec
    ) -> None:
        pass

    async def create_quota(
        self,
        name: str,
        namespace: str,
        quota: UserResourceQuantum,
    ) -> None:
        pass

    async def create_pod(
        self, name: str, namespace: str, pod: PodSpec
    ) -> None:
        pass

    async def delete_namespace(
        self,
        namespace: str,
    ) -> None:
        pass

    async def get_image_data(self) -> NodeContainers:
        return self._test_obj.nodecontents
