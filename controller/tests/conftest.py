"""Test fixtures for jupyterlab-controller tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import pytest_asyncio
import respx
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from kubernetes_asyncio.client import (
    V1Namespace,
    V1ObjectMeta,
    V1ServiceAccount,
)
from pydantic import SecretStr
from rubin.repertoire import Discovery, register_mock_discovery
from safir.testing.kubernetes import MockKubernetesApi, patch_kubernetes
from safir.testing.slack import MockSlackWebhook, mock_slack_webhook

from controller.config import Config
from controller.factory import Factory
from controller.main import create_app
from controller.models.domain.gafaelfawr import GafaelfawrUser
from controller.models.v1.prepuller import DockerSourceOptions

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


@pytest.fixture(autouse=True)
def _mock_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METRICS_APPLICATION", "controller")
    monkeypatch.setenv("METRICS_ENABLED", "false")
    monkeypatch.setenv("METRICS_MOCK", "true")


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
    nodes = read_input_node_json("base", "nodes")
    mock_kubernetes.set_nodes_for_test(nodes)
    namespace = read_input_data("base", "metadata/namespace").strip()
    for secret in read_input_secrets_json("base", "secrets"):
        await mock_kubernetes.create_namespaced_secret(namespace, secret)
    app = create_app()
    async with LifespanManager(app):
        yield app


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Return an ``httpx.AsyncClient`` configured to talk to the test app."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=TEST_BASE_URL
    ) as client:
        yield client


@pytest_asyncio.fixture
async def factory(
    config: Config,
    mock_docker: MockDockerRegistry,
    mock_kubernetes: MockKubernetesApi,
    mock_slack: MockSlackWebhook,
) -> AsyncIterator[Factory]:
    """Create a component factory for tests."""
    nodes = read_input_node_json("base", "nodes")
    mock_kubernetes.set_nodes_for_test(nodes)
    async with Factory.standalone(config) as factory:
        yield factory
        await factory.stop_background_services()


@pytest.fixture(autouse=True)
def mock_discovery(
    respx_mock: respx.Router, monkeypatch: pytest.MonkeyPatch
) -> Discovery:
    monkeypatch.setenv("REPERTOIRE_BASE_URL", "https://example.com/repertoire")
    path = Path(__file__).parent / "data" / "base" / "input" / "discovery.json"
    return register_mock_discovery(respx_mock, path)


@pytest.fixture
def mock_docker(
    config: Config, respx_mock: respx.Router
) -> MockDockerRegistry:
    assert isinstance(config.images.source, DockerSourceOptions)
    tags = read_input_json("base", "docker-tags")
    return register_mock_docker(
        respx_mock,
        host=config.images.source.registry,
        repository=config.images.source.repository,
        credentials_path=config.images.source.credentials_path,
        tags=tags,
        require_bearer=True,
    )


@pytest.fixture
def mock_gafaelfawr(
    config: Config, respx_mock: respx.Router
) -> MockGafaelfawr:
    users = read_input_users_json("base", "users")
    return register_mock_gafaelfawr(respx_mock, config.base_url, users)


@pytest.fixture
def mock_gar() -> Iterator[MockArtifactRegistry]:
    yield from patch_artifact_registry()


@pytest.fixture
def mock_kubernetes() -> Iterator[MockKubernetesApi]:
    with contextmanager(patch_kubernetes)() as mock:
        # Add a hook to create the default service account on namespace
        # creation.
        async def create_default_sa(namespace: V1Namespace) -> None:
            namespace = namespace.metadata.name
            sa = V1ServiceAccount(
                metadata=V1ObjectMeta(name="default", namespace=namespace)
            )
            await mock.create_namespaced_service_account(namespace, sa)

        mock.register_create_hook_for_test("Namespace", create_default_sa)
        yield mock


@pytest.fixture
def mock_slack(
    config: Config, respx_mock: respx.Router
) -> Iterator[MockSlackWebhook]:
    config.slack_webhook = SecretStr("https://slack.example.com/webhook")
    yield mock_slack_webhook(config.slack_webhook, respx_mock)
    config.slack_webhook = None


@pytest.fixture
def user(mock_gafaelfawr: MockGafaelfawr) -> GafaelfawrUser:
    """User to use for testing."""
    return mock_gafaelfawr.get_test_user()
