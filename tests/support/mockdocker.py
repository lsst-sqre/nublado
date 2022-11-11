from typing import List, Set

from jupyterlabcontroller.storage.docker import DockerStorageClient

from ..settings import TestObjectFactory


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
