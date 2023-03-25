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

from jupyterlabcontroller.config import Configuration
from jupyterlabcontroller.dependencies.config import configuration_dependency
from jupyterlabcontroller.factory import Factory
from jupyterlabcontroller.main import create_app

from .settings import TestObjectFactory, test_object_factory
from .support.docker import MockDockerRegistry, register_mock_docker
from .support.gafaelfawr import MockGafaelfawr, register_mock_gafaelfawr
from .support.kubernetes import MockLabKubernetesApi, patch_kubernetes

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
async def app(
    config: Configuration,
    mock_docker: MockDockerRegistry,
    mock_kubernetes: MockLabKubernetesApi,
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
async def client(
    app: FastAPI,
    config: Configuration,
) -> AsyncIterator[AsyncClient]:
    """Return an ``httpx.AsyncClient`` configured to talk to the test app."""
    async with AsyncClient(app=app, base_url=config.base_url) as client:
        yield client


@pytest_asyncio.fixture
async def factory(
    config: Configuration,
    mock_docker: MockDockerRegistry,
    mock_kubernetes: MockLabKubernetesApi,
    obj_factory: TestObjectFactory,
) -> AsyncIterator[Factory]:
    """Create a component factory for tests."""
    mock_kubernetes.set_nodes_for_test(obj_factory.nodecontents)
    async with Factory.standalone(config) as factory:
        # Currently, always start background processes since tests expect it.
        # This is temporary until tests can be refactored to decide whether
        # they want background processes running.
        await factory.start_background_services()
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
        tags=obj_factory.repocontents,
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
def mock_kubernetes() -> Iterator[MockLabKubernetesApi]:
    yield from patch_kubernetes()
