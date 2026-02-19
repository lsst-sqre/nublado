"""Test fixtures for jupyterlab-controller tests."""

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager

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
from rubin.gafaelfawr import MockGafaelfawr, register_mock_gafaelfawr
from safir.testing.kubernetes import MockKubernetesApi, patch_kubernetes
from safir.testing.slack import MockSlackWebhook, mock_slack_webhook

from nublado.controller.config import Config
from nublado.controller.factory import Factory
from nublado.controller.main import create_app
from nublado.controller.models.v1.prepuller import DockerSourceOptions

from ..support.config import configure
from ..support.constants import TEST_BASE_URL
from ..support.data import NubladoData
from ..support.docker import MockDockerRegistry, register_mock_docker
from ..support.gafaelfawr import GafaelfawrTestUser, create_gafaelfawr_user
from ..support.gar import MockArtifactRegistry, patch_artifact_registry


@pytest.fixture(autouse=True)
def _mock_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METRICS_APPLICATION", "controller")
    monkeypatch.setenv("METRICS_ENABLED", "false")
    monkeypatch.setenv("METRICS_MOCK", "true")


@pytest.fixture(autouse=True)
def _mock_introspection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "NUBLADO_CONTROLLER_REPOSITORY", "ghcr.io/lsst-sqre/nublado"
    )
    monkeypatch.setenv("NUBLADO_CONTROLLER_PULL_POLICY", "IfNotPresent")
    # Don't use setuptools_scm here, because then the JSON will not be
    # static for the tests.
    monkeypatch.setenv("NUBLADO_CONTROLLER_TAG", "11.1.1")


@pytest_asyncio.fixture
async def app(
    *,
    config: Config,
    data: NubladoData,
    mock_docker: MockDockerRegistry,
    mock_kubernetes: MockKubernetesApi,
    mock_gafaelfawr: MockGafaelfawr,
    mock_slack: MockSlackWebhook,
) -> AsyncIterator[FastAPI]:
    """Return a configured test application.

    Wraps the application in a lifespan manager so that startup and shutdown
    events are sent during test execution.
    """
    namespace = data.read_text("controller/base/metadata/namespace").strip()
    for secret in data.read_secrets("controller/base/secrets"):
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
async def config(data: NubladoData) -> Config:
    """Construct default configuration for tests."""
    return await configure(data, "standard")


@pytest_asyncio.fixture
async def factory(
    config: Config,
    data: NubladoData,
    mock_docker: MockDockerRegistry,
    mock_kubernetes: MockKubernetesApi,
    mock_slack: MockSlackWebhook,
) -> AsyncIterator[Factory]:
    """Create a component factory for tests."""
    async with Factory.standalone(config) as factory:
        yield factory
        await factory.stop_background_services()


@pytest.fixture
def mock_docker(
    config: Config, data: NubladoData, respx_mock: respx.Router
) -> MockDockerRegistry:
    assert isinstance(config.images.source, DockerSourceOptions)
    return register_mock_docker(
        respx_mock,
        host=config.images.source.registry,
        repository=config.images.source.repository,
        credentials_path=config.images.source.credentials_path,
        tags=data.read_json("controller/tags/docker"),
        require_bearer=True,
    )


@pytest_asyncio.fixture
async def mock_gafaelfawr(respx_mock: respx.Router) -> MockGafaelfawr:
    return await register_mock_gafaelfawr(respx_mock)


@pytest.fixture
def mock_gar() -> Iterator[MockArtifactRegistry]:
    yield from patch_artifact_registry()


@pytest.fixture
def mock_kubernetes(data: NubladoData) -> Iterator[MockKubernetesApi]:
    nodes = data.read_nodes("controller/nodes/standard")

    # Hook to create the default service account on namespace creation.
    async def create_default(namespace: V1Namespace) -> None:
        name = namespace.metadata.name
        account = V1ServiceAccount(metadata=V1ObjectMeta(name="default"))
        await mock.create_namespaced_service_account(name, account)

    with contextmanager(patch_kubernetes)() as mock:
        mock.set_nodes_for_test(nodes)
        mock.register_create_hook_for_test("Namespace", create_default)
        yield mock


@pytest.fixture
def mock_slack(
    config: Config, respx_mock: respx.Router
) -> Iterator[MockSlackWebhook]:
    config.slack_webhook = SecretStr("https://slack.example.com/webhook")
    yield mock_slack_webhook(config.slack_webhook, respx_mock)
    config.slack_webhook = None


@pytest.fixture
def user(
    data: NubladoData, mock_gafaelfawr: MockGafaelfawr
) -> GafaelfawrTestUser:
    """User to use for regular testing."""
    return create_gafaelfawr_user(data, "rachel", mock_gafaelfawr)


@pytest.fixture
def user_no_spawn(
    data: NubladoData, mock_gafaelfawr: MockGafaelfawr
) -> GafaelfawrTestUser:
    """User whose quota blocks them from spawning a lab."""
    return create_gafaelfawr_user(data, "ribbon", mock_gafaelfawr)
