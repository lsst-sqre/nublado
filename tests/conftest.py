"""Test fixtures for jupyterlab-controller tests."""

from __future__ import annotations

from os.path import dirname
from typing import AsyncIterator

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import AsyncClient
from safir.kubernetes import initialize_kubernetes

from jupyterlabcontroller import main
from jupyterlabcontroller.models.v1.domain.config import Config
from jupyterlabcontroller.models.v1.domain.context import (
    ContextContainer,
    RequestContext,
)
from jupyterlabcontroller.utils import get_user_namespace

from .mocks import MockDockerStorageClient, MockK8sStorageClient
from .settings import TestObjectFactory, test_object_factory

_here = dirname(__file__)

TEST_CONFIG = f"{_here}/configs/standard/config.yaml"


@pytest.fixture
def obj_factory() -> TestObjectFactory:
    filename = f"{dirname(TEST_CONFIG)}/test_objects.json"
    test_object_factory.initialize_from_file(filename)
    return test_object_factory


@pytest.fixture
def config() -> Config:
    """Change the test application configuration to point at a file that
    replaces the YAML that would usually be mounted into the container at
    ``/etc/nublado/config.yaml``.  For testing and standalone purposes, if
    the filename is not the standard location, we expect the Docker
    credentials (if any) to be in ``docker_config.json`` in the same directory
    as ``config.yaml``, and we expect objects used in testing to be in
    ``test_objects.json`` in that directory.
    """
    return Config.from_file(filename=TEST_CONFIG)


@pytest_asyncio.fixture
async def app(
    config: Config,
) -> AsyncIterator[FastAPI]:
    """Return a configured test application.

    Wraps the application in a lifespan manager so that startup and shutdown
    events are sent during test execution.
    """
    async with LifespanManager(main.app):
        yield main.app


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Return an ``httpx.AsyncClient`` configured to talk to the test app."""
    async with AsyncClient(app=app, base_url="https://example.com/") as client:
        yield client


@pytest.fixture
def k8s_storage_client(
    obj_factory: TestObjectFactory,
) -> MockK8sStorageClient:
    return MockK8sStorageClient(test_obj=obj_factory)


@pytest.fixture
def docker_storage_client(
    obj_factory: TestObjectFactory,
) -> MockDockerStorageClient:
    return MockDockerStorageClient(test_obj=obj_factory)


@pytest_asyncio.fixture
async def context_container(
    config: Config,
    client: AsyncClient,
    obj_factory: TestObjectFactory,
    k8s_storage_client: MockK8sStorageClient,
    docker_storage_client: MockDockerStorageClient,
) -> ContextContainer:
    """Return a ``ContextContainer`` configured to supply dependencies."""
    # Force K8s configuration to load
    await initialize_kubernetes()
    cc = ContextContainer.initialize(config=config, http_client=client)
    # Patch container with storage mocks
    cc.k8s_client = k8s_storage_client
    cc.docker_client = docker_storage_client
    return cc


@pytest_asyncio.fixture
async def request_context(
    context_container: ContextContainer, obj_factory: TestObjectFactory
) -> RequestContext:
    """Return a ``RequestContext`` as if we had a Request from the handler."""
    return RequestContext(
        token="token-of-affection",
        user=obj_factory.userinfos[0],
        namespace=get_user_namespace(obj_factory.userinfos[0].username),
    )
