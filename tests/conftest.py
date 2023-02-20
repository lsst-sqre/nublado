"""Test fixtures for jupyterlab-controller tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from unittest.mock import Mock

import pytest
import pytest_asyncio
import respx
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import AsyncClient
from safir.testing.kubernetes import MockKubernetesApi, patch_kubernetes

from jupyterlabcontroller.config import Configuration
from jupyterlabcontroller.dependencies.config import configuration_dependency
from jupyterlabcontroller.dependencies.context import context_dependency
from jupyterlabcontroller.factory import Factory, ProcessContext
from jupyterlabcontroller.main import create_app
from jupyterlabcontroller.storage.k8s import K8sStorageClient

from .settings import TestObjectFactory, test_object_factory
from .support.docker import MockDockerRegistry, register_mock_docker
from .support.gafaelfawr import MockGafaelfawr, register_mock_gafaelfawr

_here = Path(__file__).parent

"""Change the test application configuration to point at a file that
replaces the YAML that would usually be mounted into the container at
``/etc/nublado/config.yaml``.  For testing and standalone purposes, if
the filename is not the standard location, we expect the Docker
credentials (if any) to be in ``docker_config.json`` in the same
directory as ``config.yaml``, and we expect objects used in testing to
be in ``test_objects.json`` in that directory.
"""

# We want the prepuller state to persist across tests.


@pytest.fixture(scope="session")
def std_config_dir() -> Path:
    return Path(_here / "configs" / "standard" / "input")


@pytest.fixture(scope="session")
def std_result_dir(std_config_dir: Path) -> Path:
    return Path(std_config_dir.parent / "output")


@pytest.fixture(scope="session")
def obj_factory(std_config_dir: Path) -> TestObjectFactory:
    filename = str(std_config_dir / "test_objects.json")
    test_object_factory.initialize_from_file(filename)
    return test_object_factory


@pytest.fixture(scope="session")
def config(std_config_dir: Path) -> Configuration:
    """Construct configuration for tests.

    Overwrites the path to Docker secrets in the global configuration object
    to a value that's valid for all tests.
    """
    configuration_dependency.set_path(std_config_dir / "config.yaml")
    config = configuration_dependency.config
    config.docker_secrets_path = std_config_dir / "docker_config.json"
    return config


@pytest_asyncio.fixture
async def process_context(
    config: Configuration,
    mock_docker: MockDockerRegistry,
    mock_kubernetes: MockKubernetesApi,
    obj_factory: TestObjectFactory,
) -> ProcessContext:
    """Create a process context with mock clients."""
    k8s_client = Mock(spec=K8sStorageClient)

    async def pod_events(namespace: str, podname: str) -> AsyncIterator[str]:
        yield "some event"

    k8s_client.get_image_data.return_value = obj_factory.nodecontents
    k8s_client.get_observed_user_state.return_value = {}
    k8s_client.reflect_pod_events.side_effect = pod_events
    context = await ProcessContext.from_config(config, k8s_client)
    executor = context.prepuller_executor
    executor.state.set_remote_images(obj_factory.repocontents)
    return context


@pytest_asyncio.fixture
async def app(process_context: ProcessContext) -> AsyncIterator[FastAPI]:
    """Return a configured test application.

    Wraps the application in a lifespan manager so that startup and shutdown
    events are sent during test execution.
    """
    context_dependency.override_process_context(process_context)
    app = create_app()
    async with LifespanManager(app):
        # Ensure we've refreshed prepuller state before proceeding.
        executor = process_context.prepuller_executor
        await executor.k8s_client.refresh_state_from_k8s()
        await executor.docker_client.refresh_state_from_docker_repo()
        yield app


@pytest_asyncio.fixture
async def app_client(
    app: FastAPI,
    config: Configuration,
) -> AsyncIterator[AsyncClient]:
    """Return an ``httpx.AsyncClient`` configured to talk to the test app."""
    async with AsyncClient(app=app, base_url=config.base_url) as client:
        yield client


@pytest_asyncio.fixture
async def factory(
    config: Configuration, process_context: ProcessContext
) -> AsyncIterator[Factory]:
    """Create a component factory for tests."""
    context_dependency.override_process_context(process_context)

    # Ensure we've refreshed prepuller state before proceeding.
    executor = process_context.prepuller_executor
    await executor.k8s_client.refresh_state_from_k8s()
    await executor.docker_client.refresh_state_from_docker_repo()

    async with Factory.standalone(config, process_context) as factory:
        yield factory


@pytest.fixture
def mock_docker(
    config: Configuration,
    respx_mock: respx.Router,
    obj_factory: TestObjectFactory,
) -> MockDockerRegistry:
    return register_mock_docker(
        respx_mock,
        host=config.images.registry,
        repository=config.images.repository,
        credentials_path=config.docker_secrets_path,
        tags={n: t.digest for n, t in obj_factory.repocontents.by_tag.items()},
        require_bearer=True,
    )


@pytest.fixture
def mock_gafaelfawr(
    config: Configuration,
    respx_mock: respx.Router,
    obj_factory: TestObjectFactory,
) -> MockGafaelfawr:
    test_users = obj_factory.userinfos
    return register_mock_gafaelfawr(respx_mock, config.base_url, test_users)


@pytest.fixture
def mock_kubernetes() -> Iterator[MockKubernetesApi]:
    yield from patch_kubernetes()
