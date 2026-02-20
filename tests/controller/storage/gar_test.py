"""Tests for the Google Artifact Registry storage layer."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from google.cloud.artifactregistry_v1 import DockerImage

from nublado.controller.config import GARSourceConfig
from nublado.controller.factory import Factory
from nublado.controller.storage import gar

from ...support.config import configure
from ...support.data import NubladoData
from ...support.gar import MockArtifactRegistry


@pytest.mark.asyncio
async def test_retries(
    data: NubladoData, mock_gar: MockArtifactRegistry
) -> None:
    config = await configure(data, "gar")
    assert isinstance(config.images.source, GARSourceConfig)
    mock_gar.fail_for_test()
    known_images = data.read_json("controller/tags/gar")
    mock_gar.add_images_for_test(DockerImage(**i) for i in known_images)

    # Find all the known tags in the relevant test images.
    tags: list[str] = []
    for image in known_images:
        if config.images.source.image in image["uri"]:
            tags.extend(image["tags"])

    # The first request will fail with an exception, but the second attempt
    # will succeed. This should be hidden by the storage layer. Reduce the
    # retry interval to zero to not slow down the test.
    with patch.object(gar, "GAR_RETRY_DELAY", new=timedelta(seconds=0)):
        async with Factory.standalone(config) as factory:
            storage = factory.create_gar_storage()
            images = await storage.list_images(config.images.source)

    seen = [i.tag for i in images.all_images(hide_arch_specific=False)]
    assert sorted(seen) == sorted(tags)
