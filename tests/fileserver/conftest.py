"""Test fixtures for jupyterlab-controller tests that require a running
fileserver.  This requires a different application, configuration, factory,
and so on."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import AsyncClient
from kubernetes_asyncio.client import V1Namespace, V1ObjectMeta
from safir.testing.kubernetes import MockKubernetesApi, patch_kubernetes
from safir.testing.slack import MockSlackWebhook

from jupyterlabcontroller.config import Config
from jupyterlabcontroller.factory import Factory
from jupyterlabcontroller.main import create_app

from ..settings import TestObjectFactory, test_object_factory
from ..support.config import configure
from ..support.constants import TEST_BASE_URL
from ..support.docker import MockDockerRegistry
from ..support.gafaelfawr import MockGafaelfawr


@pytest.fixture
def std_config_dir() -> Path:
    return Path(
        Path(__file__).parent.parent / "configs" / "fileserver" / "input"
    )


@pytest.fixture
def std_result_dir(std_config_dir: Path) -> Path:
    return Path(std_config_dir.parent / "output")


@pytest.fixture
def obj_factory(std_config_dir: Path) -> TestObjectFactory:
    filename = str(std_config_dir / "test_objects.json")
    test_object_factory.initialize_from_file(filename)
    return test_object_factory


@pytest_asyncio.fixture
async def config() -> Config:
    """Construct default configuration for tests."""
    return configure("fileserver")


@pytest_asyncio.fixture
async def app(
    config: Config,
    mock_docker: MockDockerRegistry,
    mock_kubernetes: MockKubernetesApi,
    mock_gafaelfawr: MockGafaelfawr,
    mock_slack: MockSlackWebhook,
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
    # Create a namespace for fileserver objects.
    await mock_kubernetes.create_namespace(
        V1Namespace(metadata=V1ObjectMeta(name=config.fileserver.namespace))
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
def mock_kubernetes() -> Iterator[MockKubernetesApi]:
    yield from patch_kubernetes()
