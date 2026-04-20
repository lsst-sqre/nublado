"""Test for the Docker API client."""

import os

import pytest
import respx
from httpx import AsyncClient
from structlog import get_logger

from nublado.exceptions import DockerInvalidUrlError
from nublado.models.images import DockerSource
from nublado.storage.docker import DockerStorageClient

from ..support.data import NubladoData
from ..support.docker import register_mock_docker


@pytest.fixture
def docker_client(source: DockerSource) -> DockerStorageClient:
    return DockerStorageClient(
        source.credentials_path, AsyncClient(), get_logger(__name__)
    )


@pytest.fixture
def source(data: NubladoData) -> DockerSource:
    source = data.read_pydantic(DockerSource, "storage/docker-source")
    source.credentials_path = data.path("registry/docker-creds.json")
    return source


@pytest.mark.asyncio
async def test_api(
    source: DockerSource,
    docker_client: DockerStorageClient,
    respx_mock: respx.Router,
) -> None:
    tag_names = {
        "w_2021_21",
        "w_2021_21-arm64",
        "w_2021_21-amd64",
        "w_2021_22",
        "w_2021_22-amd64",
        "d_2021_06_14-amd64",
        "d_2021_06_15",
    }
    tags = {t: "sha256:" + os.urandom(32).hex() for t in tag_names}
    register_mock_docker(respx_mock, source, tags, paginate=True)
    assert await docker_client.list_tags(source) == tag_names
    digest = await docker_client.get_image_digest(source, "w_2021_21")
    assert digest == tags["w_2021_21"]
    digest = await docker_client.get_image_digest(source, "w_2021_22")
    assert digest == tags["w_2021_22"]


@pytest.mark.asyncio
async def test_api_nonpaginated(
    source: DockerSource,
    docker_client: DockerStorageClient,
    respx_mock: respx.Router,
) -> None:
    tag_names = {"w_2021_21", "w_2021_22", "d_2021_06_14", "d_2021_06_15"}
    tags = {t: "sha256:" + os.urandom(32).hex() for t in tag_names}
    register_mock_docker(respx_mock, source, tags, paginate=False)
    assert await docker_client.list_tags(source) == tag_names
    digest = await docker_client.get_image_digest(source, "w_2021_21")
    assert digest == tags["w_2021_21"]
    digest = await docker_client.get_image_digest(source, "w_2021_22")
    assert digest == tags["w_2021_22"]


@pytest.mark.asyncio
async def test_bearer_auth(
    source: DockerSource,
    docker_client: DockerStorageClient,
    respx_mock: respx.Router,
) -> None:
    tags = {"r23_0_4": "sha256:" + os.urandom(32).hex()}
    register_mock_docker(respx_mock, source, tags, require_bearer=True)
    assert await docker_client.list_tags(source) == {"r23_0_4"}
    digest = await docker_client.get_image_digest(source, "r23_0_4")
    assert digest == tags["r23_0_4"]


@pytest.mark.asyncio
async def test_duplicate_url(
    source: DockerSource,
    docker_client: DockerStorageClient,
    respx_mock: respx.Router,
) -> None:
    tag_names = {"w_2021_21", "w_2021_22", "d_2021_06_14", "d_2021_06_15"}
    tags = {t: "sha256:" + os.urandom(32).hex() for t in tag_names}
    register_mock_docker(
        respx_mock, source, tags, paginate=True, duplicate_url=True
    )
    with pytest.raises(DockerInvalidUrlError):
        await docker_client.list_tags(source)
