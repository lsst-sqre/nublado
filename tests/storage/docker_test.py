"""Test for the Docker API client."""

from __future__ import annotations

import os
from base64 import b64encode

import pytest
import respx
import structlog
from httpx import AsyncClient

from jupyterlabcontroller.models.domain.docker import DockerCredentials
from jupyterlabcontroller.storage.docker import DockerStorageClient

from ..support.docker import mock_docker


@pytest.mark.asyncio
async def test_api(respx_mock: respx.Router) -> None:
    tag_names = {"w_2021_21", "w_2021_22", "d_2021_06_14", "d_2021_06_15"}
    tags = {t: "sha256:" + os.urandom(32).hex() for t in tag_names}
    mock = mock_docker(
        respx_mock,
        host="registry.hub.docker.com",
        repository="lsstsqre/sciplat-lab",
        tags=tags,
    )

    docker = DockerStorageClient(
        structlog.get_logger(__name__),
        "registry.hub.docker.com",
        "lsstsqre/sciplat-lab",
        "recommended",
        AsyncClient(),
        DockerCredentials(
            registry_host="registry.hub.docker.com",
            username=mock.username,
            password=mock.password,
            base64_auth=b64encode(
                f"{mock.username}:{mock.password}".encode()
            ).decode(),
        ),
    )
    assert set(await docker.list_tags()) == tag_names
    assert await docker.get_image_digest("w_2021_21") == tags["w_2021_21"]
    assert await docker.get_image_digest("w_2021_22") == tags["w_2021_22"]


@pytest.mark.asyncio
async def test_bearer_auth(respx_mock: respx.Router) -> None:
    tags = {"r23_0_4": "sha256:" + os.urandom(32).hex()}
    mock = mock_docker(
        respx_mock,
        host="registry.hub.docker.com",
        repository="lsstsqre/sciplat-lab",
        tags=tags,
        require_bearer=True,
    )

    docker = DockerStorageClient(
        structlog.get_logger(__name__),
        "registry.hub.docker.com",
        "lsstsqre/sciplat-lab",
        "recommended",
        AsyncClient(),
        DockerCredentials(
            registry_host="registry.hub.docker.com",
            username=mock.username,
            password=mock.password,
            base64_auth=b64encode(
                f"{mock.username}:{mock.password}".encode()
            ).decode(),
        ),
    )
    assert await docker.list_tags() == ["r23_0_4"]
    assert await docker.get_image_digest("r23_0_4") == tags["r23_0_4"]
