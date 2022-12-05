from typing import List

from jupyterlabcontroller.models.domain.prepuller import TagMap
from jupyterlabcontroller.storage.docker import DockerStorageClient

from ..settings import TestObjectFactory, test_object_factory


class MockDockerStorageClient(DockerStorageClient):
    def __init__(self, test_obj: TestObjectFactory) -> None:
        self._test_obj = test_obj

    async def list_tags(self, authenticate: bool = True) -> List[str]:
        return sorted(list(self._test_obj.repocontents.by_tag.keys()))

    async def list_image_hash(
        self, tag: str, authenticate: bool = True
    ) -> str:
        default_hash: str = "sha256:abcd"
        for dig in self._test_obj.repocontents.by_digest:
            if tag in self._test_obj.repocontents.by_digest[dig]:
                return dig
        return default_hash

    async def get_tag_map(self) -> TagMap:
        return self._test_obj.repocontents


mock_docker_dependency = MockDockerStorageClient(test_obj=test_object_factory)
