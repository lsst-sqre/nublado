from typing import List

from jupyterlabcontroller.storage.docker import DockerStorageClient

from ..settings import TestObjectFactory, test_object_factory


class MockDockerStorageClient(DockerStorageClient):
    def __init__(
        self, test_obj: TestObjectFactory, recommended_tag: str = "recommended"
    ) -> None:
        self._test_obj = test_obj
        self.recommended_tag = recommended_tag

    async def list_tags(self, registry: str, repository: str) -> List[str]:
        return sorted(list(self._test_obj.repocontents.by_tag.keys()))

    async def get_image_digest(
        self, registry: str, repository: str, tag: str
    ) -> str:
        default_hash: str = "sha256:abcd"
        tm = self._test_obj.repocontents
        digestmap = tm.by_digest
        for digest in digestmap:
            tag_objs = digestmap[digest]
            if tag in [x.tag for x in tag_objs]:
                return digest
        return default_hash


mock_docker_dependency = MockDockerStorageClient(test_obj=test_object_factory)
