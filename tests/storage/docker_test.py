"""Test for the Docker API client."""

from __future__ import annotations

import os

import pytest
import respx

from jupyterlabcontroller.config import Configuration
from jupyterlabcontroller.factory import Factory

from ..support.docker import mock_docker


@pytest.mark.asyncio
async def test_api(
    config: Configuration, factory: Factory, respx_mock: respx.Router
) -> None:
    tag_names = {"w_2021_21", "w_2021_22", "d_2021_06_14", "d_2021_06_15"}
    tags = {t: "sha256:" + os.urandom(32).hex() for t in tag_names}
    docker_credentials = factory.get_docker_credentials()
    credentials = docker_credentials.get(config.images.registry)
    assert credentials
    mock_docker(
        respx_mock,
        host=config.images.registry,
        repository=config.images.repository,
        credentials=credentials,
        tags=tags,
    )
    docker = factory.create_docker_storage()
    assert set(await docker.list_tags()) == tag_names
    assert await docker.get_image_digest("w_2021_21") == tags["w_2021_21"]
    assert await docker.get_image_digest("w_2021_22") == tags["w_2021_22"]


@pytest.mark.asyncio
async def test_bearer_auth(
    config: Configuration, factory: Factory, respx_mock: respx.Router
) -> None:
    assert config.images.docker
    tags = {"r23_0_4": "sha256:" + os.urandom(32).hex()}
    docker_credentials = factory.get_docker_credentials()
    credentials = docker_credentials.get(config.images.docker.registry)
    assert credentials
    mock_docker(
        respx_mock,
        host=config.images.docker.registry,
        repository=config.images.docker.repository,
        credentials=credentials,
        tags=tags,
        require_bearer=True,
    )
    docker = factory.create_docker_storage()
    assert await docker.list_tags() == ["r23_0_4"]
    assert await docker.get_image_digest("r23_0_4") == tags["r23_0_4"]
