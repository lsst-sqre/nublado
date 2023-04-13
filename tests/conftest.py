"""Test fixtures for jupyterlab-controller tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
import respx
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import AsyncClient
from safir.testing.slack import MockSlackWebhook, mock_slack_webhook

from jupyterlabcontroller.config import Config
from jupyterlabcontroller.factory import Factory
from jupyterlabcontroller.main import create_app
from jupyterlabcontroller.models.v1.prepuller_config import DockerSourceConfig

from .settings import TestObjectFactory, test_object_factory
from .support.config import configure
from .support.constants import TEST_BASE_URL
from .support.docker import MockDockerRegistry, register_mock_docker
from .support.gafaelfawr import MockGafaelfawr, register_mock_gafaelfawr
from .support.gar import MockArtifactRegistry, patch_artifact_registry
from .support.kubernetes import MockKubernetesApi, patch_kubernetes


@pytest.fixture(scope="session")
def std_config_dir() -> Path:
    return Path(Path(__file__).parent / "configs" / "standard" / "input")


@pytest.fixture(scope="session")
def std_result_dir(std_config_dir: Path) -> Path:
    return Path(std_config_dir.parent / "output")


@pytest.fixture(scope="session")
def obj_factory(std_config_dir: Path) -> TestObjectFactory:
    filename = str(std_config_dir / "test_objects.json")
    test_object_factory.initialize_from_file(filename)
    return test_object_factory


@pytest.fixture(scope="session")
def config() -> Config:
    """Construct default configuration for tests."""
    return configure("standard")


@pytest_asyncio.fixture
async def app(
    config: Config,
    mock_docker: MockDockerRegistry,
    mock_kubernetes: MockKubernetesApi,
    mock_gafaelfawr: MockGafaelfawr,
    obj_factory: TestObjectFactory,
) -> AsyncIterator[FastAPI]:
    """Return a configured test application.

    Wraps the application in a lifespan manager so that startup and shutdown
    events are sent during test execution.
    """
    mock_kubernetes.set_nodes_for_test(obj_factory.nodecontents)
    for secret in obj_factory.secrets:
        await mock_kubernetes.create_namespaced_secret(
            config.lab.namespace_prefix, secret
        )
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
    obj_factory: TestObjectFactory,
) -> AsyncIterator[Factory]:
    """Create a component factory for tests."""
    mock_kubernetes.set_nodes_for_test(obj_factory.nodecontents)
    async with Factory.standalone(config) as factory:
        yield factory


@pytest.fixture
def mock_docker(
    config: Config,
    respx_mock: respx.Router,
    obj_factory: TestObjectFactory,
) -> MockDockerRegistry:
    assert isinstance(config.images.source, DockerSourceConfig)
    return register_mock_docker(
        respx_mock,
        host=config.images.source.registry,
        repository=config.images.source.repository,
        credentials_path=config.docker_secrets_path,
        tags=obj_factory.repocontents,
        require_bearer=True,
    )


@pytest.fixture
def mock_gafaelfawr(
    config: Config,
    respx_mock: respx.Router,
    obj_factory: TestObjectFactory,
) -> MockGafaelfawr:
    test_users = obj_factory.userinfos
    return register_mock_gafaelfawr(respx_mock, config.base_url, test_users)


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
