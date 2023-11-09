"""Test for the Docker API client."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest
import respx

from controller.config import Config
from controller.factory import Factory
from controller.models.domain.docker import DockerCredentials
from controller.models.v1.prepuller_config import DockerSourceConfig
from controller.storage.docker import DockerCredentialStore

from ..support.docker import register_mock_docker


@pytest.mark.asyncio
async def test_api(
    config: Config, factory: Factory, respx_mock: respx.Router
) -> None:
    tag_names = {"w_2021_21", "w_2021_22", "d_2021_06_14", "d_2021_06_15"}
    tags = {t: "sha256:" + os.urandom(32).hex() for t in tag_names}
    assert isinstance(config.images.source, DockerSourceConfig)
    register_mock_docker(
        respx_mock,
        host=config.images.source.registry,
        repository=config.images.source.repository,
        credentials_path=config.images.source.credentials_path,
        tags=tags,
    )
    docker = factory.create_docker_storage()
    assert set(await docker.list_tags(config.images.source)) == tag_names
    digest = await docker.get_image_digest(config.images.source, "w_2021_21")
    assert digest == tags["w_2021_21"]
    digest = await docker.get_image_digest(config.images.source, "w_2021_22")
    assert digest == tags["w_2021_22"]


@pytest.mark.asyncio
async def test_bearer_auth(
    config: Config, factory: Factory, respx_mock: respx.Router
) -> None:
    assert isinstance(config.images.source, DockerSourceConfig)
    tags = {"r23_0_4": "sha256:" + os.urandom(32).hex()}
    register_mock_docker(
        respx_mock,
        host=config.images.source.registry,
        repository=config.images.source.repository,
        credentials_path=config.images.source.credentials_path,
        tags=tags,
        require_bearer=True,
    )
    docker = factory.create_docker_storage()
    assert await docker.list_tags(config.images.source) == ["r23_0_4"]
    digest = await docker.get_image_digest(config.images.source, "r23_0_4")
    assert digest == tags["r23_0_4"]


def test_credential_store(tmp_path: Path) -> None:
    store = DockerCredentialStore({})
    assert store.get("example.com") is None
    credentials = DockerCredentials(username="foo", password="blahblah")
    store.set("example.com", credentials)
    assert store.get("example.com") == credentials
    assert store.get("foo.example.com") == credentials
    assert store.get("example.org") is None
    other_credentials = DockerCredentials(username="u", password="p")
    store.set("example.org", other_credentials)

    store_path = tmp_path / "credentials.json"
    store.save(store_path)
    with store_path.open("r") as f:
        data = json.load(f)
    assert data == {
        "auths": {
            "example.com": {
                "username": "foo",
                "password": "blahblah",
                "auth": base64.b64encode(b"foo:blahblah").decode(),
            },
            "example.org": {
                "username": "u",
                "password": "p",
                "auth": base64.b64encode(b"u:p").decode(),
            },
        }
    }

    store = DockerCredentialStore.from_path(store_path)
    assert store.get("example.com") == credentials
    assert store.get("foo.example.com") == credentials
    assert store.get("example.org") == other_credentials
