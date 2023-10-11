"""Test fixtures for jupyterlab-controller tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
import respx
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import AsyncClient
from safir.testing.kubernetes import MockKubernetesApi, patch_kubernetes
from safir.testing.slack import MockSlackWebhook, mock_slack_webhook

from jupyterlabcontroller.config import Config
from jupyterlabcontroller.factory import Factory
from jupyterlabcontroller.main import create_app
from jupyterlabcontroller.models.domain.gafaelfawr import GafaelfawrUser
from jupyterlabcontroller.models.v1.prepuller_config import DockerSourceConfig

from .support.config import configure
from .support.constants import TEST_BASE_URL
from .support.data import (
    read_input_data,
    read_input_json,
    read_input_node_json,
    read_input_secrets_json,
    read_input_users_json,
)
from .support.docker import MockDockerRegistry, register_mock_docker
from .support.gafaelfawr import MockGafaelfawr, register_mock_gafaelfawr
from .support.gar import MockArtifactRegistry, patch_artifact_registry


@pytest_asyncio.fixture
async def config() -> Config:
    """Construct default configuration for tests."""
    return await configure("standard")


@pytest_asyncio.fixture
async def app(
    config: Config,
    mock_docker: MockDockerRegistry,
    mock_kubernetes: MockKubernetesApi,
    mock_gafaelfawr: MockGafaelfawr,
    mock_slack: MockSlackWebhook,
) -> AsyncIterator[FastAPI]:
    """Return a configured test application.

    Wraps the application in a lifespan manager so that startup and shutdown
    events are sent during test execution.
    """
    nodes = read_input_node_json("base", "nodes.json")
    mock_kubernetes.set_nodes_for_test(nodes)
    namespace = read_input_data("base", "metadata/namespace").strip()
    for secret in read_input_secrets_json("base", "secrets.json"):
        await mock_kubernetes.create_namespaced_secret(namespace, secret)
    app = create_app()
    async with LifespanManager(app):
        yield app


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Return an ``httpx.AsyncClient`` configured to talk to the test app."""
    async with AsyncClient(app=app, base_url=TEST_BASE_URL) as client:
        yield client


@pytest_asyncio.fixture
async def factory(
    config: Config,
    mock_docker: MockDockerRegistry,
    mock_kubernetes: MockKubernetesApi,
    mock_slack: MockSlackWebhook,
) -> AsyncIterator[Factory]:
    """Create a component factory for tests."""
    nodes = read_input_node_json("base", "nodes.json")
    mock_kubernetes.set_nodes_for_test(nodes)
    async with Factory.standalone(config) as factory:
        yield factory


@pytest.fixture
def mock_docker(
    config: Config, respx_mock: respx.Router
) -> MockDockerRegistry:
    assert isinstance(config.images.source, DockerSourceConfig)
    tags = read_input_json("base", "docker-tags.json")
    return register_mock_docker(
        respx_mock,
        host=config.images.source.registry,
        repository=config.images.source.repository,
        credentials_path=config.docker_secrets_path,
        tags=tags,
        require_bearer=True,
    )


@pytest.fixture
def mock_gafaelfawr(
    config: Config, respx_mock: respx.Router
) -> MockGafaelfawr:
    users = read_input_users_json("base", "users.json")
    return register_mock_gafaelfawr(respx_mock, config.base_url, users)


@pytest.fixture
def mock_gar() -> Iterator[MockArtifactRegistry]:
    yield from patch_artifact_registry()


@pytest.fixture
def mock_kubernetes() -> Iterator[MockKubernetesApi]:
    yield from patch_kubernetes()


@pytest.fixture
def mock_slack(
    config: Config, respx_mock: respx.Router
) -> Iterator[MockSlackWebhook]:
    config.slack_webhook = "https://slack.example.com/webhook"
    yield mock_slack_webhook(config.slack_webhook, respx_mock)
    config.slack_webhook = None


@pytest.fixture
def user(mock_gafaelfawr: MockGafaelfawr) -> GafaelfawrUser:
    """User to use for testing."""
    return mock_gafaelfawr.get_test_user()
