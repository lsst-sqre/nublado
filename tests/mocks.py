from typing import Dict, List, Set

from jupyterlabcontroller.storage.docker import DockerStorageClient
from jupyterlabcontroller.storage.k8s import (
    K8sStorageClient,
    NetworkPolicySpec,
    NodeContainers,
    PodSpec,
    Secret,
    UserQuota,
)

from .settings import TestObjectFactory


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
        quota: UserQuota,
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


class MockDockerStorageClient(DockerStorageClient):
    def __init__(self, test_obj: TestObjectFactory) -> None:
        self._test_obj = test_obj

    async def list_tags(self, authenticate: bool = True) -> List[str]:
        alltags: Set[str] = set()
        for node in self._test_obj.nodecontents:
            nc = self._test_obj.test_objects["node_contents"][node]
            for n in nc["names"]:
                if "@" in n:
                    continue  # Skip anything with a hash
                alltags.add(n)
        return sorted(list(alltags), reverse=True)

    async def list_image_hash(
        self, tag: str, authenticate: bool = True
    ) -> str:
        default_hash: str = "sha256:abcd"
        for node in self._test_obj.test_objects["node_contents"]:
            nc = self._test_obj.test_objects["node_contents"][node]
            if tag in nc["names"]:
                for n in nc["names"]:
                    if "@" in n:
                        fullhash = n.split["@"][1]
                        digest = fullhash.split[":"][1]
                        return f"sha256:{digest}"
        return default_hash
