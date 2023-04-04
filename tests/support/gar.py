"""Mock out the Google Artifact Registry API for tests."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import AsyncIterator, Iterator
from typing import Any
from unittest.mock import Mock, patch

from google.cloud import artifactregistry_v1
from google.cloud.artifactregistry_v1 import (
    ArtifactRegistryAsyncClient,
    DockerImage,
    ListDockerImagesRequest,
)

__all__ = [
    "MockArtifactRegistry",
    "patch_artifact_registry",
]


class MockArtifactRegistry(Mock):
    """Mock Google Artifact Registry for testing."""

    def __init__(self) -> None:
        super().__init__(spec=ArtifactRegistryAsyncClient)
        self._images: defaultdict[str, list[DockerImage]] = defaultdict(list)

    def add_image_for_test(self, parent: str, image: DockerImage) -> None:
        """Add an image to the set of known images in the mock registry.

        Parameters
        ----------
        parent
            Parent search key that should uncover this image.
        image
            Image to add.
        """
        self._images[parent].append(image)

    async def list_docker_images(
        self,
        request: ListDockerImagesRequest,
    ) -> AsyncIterator[DockerImage]:
        """Retrieve the known list of images matching the request.

        Parameters
        ----------
        request
            Image list request. Only the ``parent`` field is used.

        Yields
        ------
        DockerImage
            Next image matching the request.

        Notes
        -----
        The Google API documentation for this function is wrong. It claims
        that it's a non-async function returning an async iterator, but the
        source code confirms that it is an async function that returns an
        async iterator. (This is an odd construction, but it's done this way
        because the method call preloads the first page of data, and thus
        itself has to be async.)
        """

        async def iterator() -> AsyncIterator[DockerImage]:
            for image in self._images[request.parent]:
                yield image

        return iterator()

    def _get_child_mock(self, /, **kwargs: Any) -> Mock:
        return Mock(**kwargs)


def patch_artifact_registry() -> Iterator[MockArtifactRegistry]:
    """Replace the Google Artifact Registry API with a mock class.

    Returns
    -------
    MockArtifactRegistry
        Mock Artifact Registry API object.
    """
    mock_api = MockArtifactRegistry()
    name = "ArtifactRegistryAsyncClient"
    with patch.object(artifactregistry_v1, name) as mock:
        mock.return_value = mock_api
        yield mock_api
