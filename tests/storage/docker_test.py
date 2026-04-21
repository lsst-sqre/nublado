"""Test for the Docker API client."""

import os

import pytest
import respx
from httpx import AsyncClient
from structlog import get_logger

from nublado.exceptions import DockerInvalidUrlError
from nublado.models.docker import DockerCredentialStore
from nublado.models.images import DockerSource
from nublado.storage.docker import DockerStorageClient

from ..support.data import NubladoData
from ..support.docker import register_mock_docker


@pytest.fixture
def credential_store(data: NubladoData) -> DockerCredentialStore:
    path = data.path("registry/docker-creds.json")
    return DockerCredentialStore.from_path(path)


@pytest.fixture
def docker_client(
    data: NubladoData, source: DockerSource
) -> DockerStorageClient:
    credential_path = data.path("registry/docker-creds.json")
    logger = get_logger(__name__)
    return DockerStorageClient(credential_path, AsyncClient(), logger)


@pytest.fixture
def source(data: NubladoData) -> DockerSource:
    return data.read_pydantic(DockerSource, "storage/docker-source")


@pytest.mark.asyncio
async def test_api(
    *,
    source: DockerSource,
    credential_store: DockerCredentialStore,
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
    register_mock_docker(
        respx_mock, source, credential_store, tags=tags, paginate=True
    )
    assert await docker_client.list_tags(source) == tag_names
    digest = await docker_client.get_image_digest(source, "w_2021_21")
    assert digest == tags["w_2021_21"]
    digest = await docker_client.get_image_digest(source, "w_2021_22")
    assert digest == tags["w_2021_22"]


@pytest.mark.asyncio
async def test_api_nonpaginated(
    *,
    source: DockerSource,
    credential_store: DockerCredentialStore,
    docker_client: DockerStorageClient,
    respx_mock: respx.Router,
) -> None:
    tag_names = {"w_2021_21", "w_2021_22", "d_2021_06_14", "d_2021_06_15"}
    tags = {t: "sha256:" + os.urandom(32).hex() for t in tag_names}
    register_mock_docker(
        respx_mock, source, credential_store, tags=tags, paginate=False
    )
    assert await docker_client.list_tags(source) == tag_names
    digest = await docker_client.get_image_digest(source, "w_2021_21")
    assert digest == tags["w_2021_21"]
    digest = await docker_client.get_image_digest(source, "w_2021_22")
    assert digest == tags["w_2021_22"]


@pytest.mark.asyncio
async def test_bearer_auth(
    *,
    source: DockerSource,
    credential_store: DockerCredentialStore,
    docker_client: DockerStorageClient,
    respx_mock: respx.Router,
) -> None:
    tags = {"r23_0_4": "sha256:" + os.urandom(32).hex()}
    register_mock_docker(
        respx_mock, source, credential_store, tags=tags, require_bearer=True
    )
    assert await docker_client.list_tags(source) == {"r23_0_4"}
    digest = await docker_client.get_image_digest(source, "r23_0_4")
    assert digest == tags["r23_0_4"]


@pytest.mark.asyncio
async def test_duplicate_url(
    *,
    source: DockerSource,
    credential_store: DockerCredentialStore,
    docker_client: DockerStorageClient,
    respx_mock: respx.Router,
) -> None:
    tag_names = {"w_2021_21", "w_2021_22", "d_2021_06_14", "d_2021_06_15"}
    tags = {t: "sha256:" + os.urandom(32).hex() for t in tag_names}
    register_mock_docker(
        respx_mock,
        source,
        credential_store,
        tags=tags,
        paginate=True,
        duplicate_url=True,
    )
    with pytest.raises(DockerInvalidUrlError):
        await docker_client.list_tags(source)
