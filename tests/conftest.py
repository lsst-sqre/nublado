"""Test fixtures for jupyterlab-controller tests."""

from __future__ import annotations

import asyncio
from copy import copy
from pathlib import Path
from typing import AsyncIterator, Iterator

import pytest
import pytest_asyncio
import structlog
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import AsyncClient
from safir import logging
from safir.kubernetes import initialize_kubernetes
from structlog.stdlib import BoundLogger

from jupyterlabcontroller.config import Configuration
from jupyterlabcontroller.dependencies.config import configuration_dependency
from jupyterlabcontroller.dependencies.prepull import (
    prepuller_manager_dependency,
)
from jupyterlabcontroller.dependencies.storage import (
    docker_storage_dependency,
    k8s_storage_dependency,
)
from jupyterlabcontroller.main import create_app
from jupyterlabcontroller.models.context import Context
from jupyterlabcontroller.models.domain.docker import DockerCredentialsMap
from jupyterlabcontroller.models.domain.storage import StorageClientBundle
from jupyterlabcontroller.models.domain.usermap import UserMap
from jupyterlabcontroller.models.v1.lab import UserInfo
from jupyterlabcontroller.services.prepuller import PrepullerManager
from jupyterlabcontroller.storage.docker import DockerStorageClient
from jupyterlabcontroller.storage.k8s import K8sStorageClient

from .settings import TestObjectFactory, test_object_factory
from .support.mockdocker import MockDockerStorageClient
from .support.mockk8s import MockK8sStorageClient

_here = Path(__file__).parent

CONFIG_DIR = Path(_here / "configs/standard")

"""Change the test application configuration to point at a file that
replaces the YAML that would usually be mounted into the container at
``/etc/nublado/config.yaml``.  For testing and standalone purposes, if
the filename is not the standard location, we expect the Docker
credentials (if any) to be in ``docker_config.json`` in the same
directory as ``config.yaml``, and we expect objects used in testing to
be in ``test_objects.json`` in that directory.
"""


@pytest.fixture
def logger() -> BoundLogger:
    return structlog.get_logger(logging.logger_name)


@pytest.fixture
def obj_factory() -> TestObjectFactory:
    filename = str(CONFIG_DIR / "test_objects.json")
    test_object_factory.initialize_from_file(filename)
    return test_object_factory


@pytest.fixture
def http_client() -> AsyncClient:
    return AsyncClient(follow_redirects=True)


@pytest_asyncio.fixture
async def docker_credentials(logger: BoundLogger) -> DockerCredentialsMap:
    filename = str(CONFIG_DIR / "docker_config.json")
    docker_creds = DockerCredentialsMap(filename=filename, logger=logger)
    return docker_creds


@pytest.fixture
def config() -> Configuration:
    configuration_dependency.set_filename(f"{CONFIG_DIR}/config.yaml")
    return configuration_dependency.config


@pytest.fixture(scope="session")
def event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    """Increase the scope of the event loop to the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def k8s_storage_client(
    obj_factory: TestObjectFactory,
    logger: BoundLogger,
) -> K8sStorageClient:
    # Force K8s configuration to load
    await initialize_kubernetes()
    k8s_storage_dependency.set_state(
        k8s_client=MockK8sStorageClient(test_obj=obj_factory),
        logger=logger,
    )
    return k8s_storage_dependency.k8s_client


@pytest_asyncio.fixture
async def docker_storage_client(
    obj_factory: TestObjectFactory,
    config: Configuration,
    docker_credentials: DockerCredentialsMap,
    logger: BoundLogger,
    http_client: AsyncClient,
) -> DockerStorageClient:
    docker_storage_dependency.set_state(
        docker_client=MockDockerStorageClient(test_obj=obj_factory),
        logger=logger,
        http_client=http_client,
        config=config,
    )
    return docker_storage_dependency.docker_client


@pytest_asyncio.fixture
async def prepuller_manager(
    config: Configuration,
    k8s_storage_client: K8sStorageClient,
    docker_storage_client: DockerStorageClient,
    logger: BoundLogger,
) -> PrepullerManager:
    prepuller_manager_dependency.set_state(
        logger=logger,
        config=config,
        k8s_client=k8s_storage_client,
        docker_client=docker_storage_client,
    )
    return prepuller_manager_dependency.prepuller_manager


@pytest_asyncio.fixture
async def app(
    k8s_storage_client: K8sStorageClient,
    docker_storage_client: DockerStorageClient,
) -> AsyncIterator[FastAPI]:
    """Return a configured test application.

    Wraps the application in a lifespan manager so that startup and shutdown
    events are sent during test execution.
    """
    app = create_app(
        config_dir=str(CONFIG_DIR),
        storage_clients=StorageClientBundle(
            k8s_client=k8s_storage_client,
            docker_client=docker_storage_client,
        ),
    )
    async with LifespanManager(app):
        yield app


@pytest_asyncio.fixture
async def app_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Return an ``httpx.AsyncClient`` configured to talk to the test app."""
    async with AsyncClient(app=app, base_url="https://example.com/") as client:
        yield client


@pytest_asyncio.fixture
async def user_map(obj_factory: TestObjectFactory) -> UserMap:
    return obj_factory.usermap


@pytest_asyncio.fixture
async def context(
    config: Configuration,
    http_client: AsyncClient,
    obj_factory: TestObjectFactory,
    k8s_storage_client: K8sStorageClient,
    docker_storage_client: DockerStorageClient,
    user_map: UserMap,
    logger: BoundLogger,
) -> Context:
    """Return a ``Context`` configured to supply dependencies."""
    cc = Context.initialize(
        config=config,
        http_client=http_client,
        logger=logger,
        k8s_client=k8s_storage_client,
        docker_client=docker_storage_client,
        user_map=user_map,
    )

    return cc


@pytest_asyncio.fixture
async def user(obj_factory: TestObjectFactory) -> UserInfo:
    return obj_factory.userinfos[0]


@pytest_asyncio.fixture
async def username(user: UserInfo) -> str:
    return user.username


@pytest_asyncio.fixture
async def user_context(
    context: Context, user: UserInfo, obj_factory: TestObjectFactory
) -> Context:
    """Return Context with user data."""
    cp = copy(context)
    cp.token = "token-of-affection"
    cp.token_scopes = ["exec:notebook"]
    cp.user = user
    assert cp.user is not None
    cp.namespace = f"{context.namespace}-{cp.user.username}"
    return cp


@pytest_asyncio.fixture
async def admin_context(
    context: Context, obj_factory: TestObjectFactory
) -> Context:
    """Return Context with user data."""
    cp = copy(context)
    cp.token = "token-of-authority"
    cp.token_scopes = ["admin:jupyterlab"]
    cp.user = obj_factory.userinfos[1]
    cp.namespace = f"{context.namespace}-{cp.user.username}"
    return cp
