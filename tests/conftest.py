"""Test fixtures for jupyterlab-controller tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from fastapi import FastAPI, Request
from httpx import AsyncClient
from starlette.datastructures import Headers

from jupyterlabcontroller.config import Configuration
from jupyterlabcontroller.dependencies.config import configuration_dependency
from jupyterlabcontroller.dependencies.context import ContextDependency
from jupyterlabcontroller.factory import Context, Factory
from jupyterlabcontroller.main import create_app

from .settings import TestObjectFactory, test_object_factory
from .support.mockcontextdependency import MockContextDependency

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


@pytest_asyncio.fixture(scope="session")
async def context_dependency(
    config: Configuration, obj_factory: TestObjectFactory
) -> ContextDependency:
    dep = MockContextDependency(test_obj=obj_factory)
    await dep.initialize(config=config)
    false_context = await dep(request=make_request(token="prepuller-state"))
    px = false_context.prepuller_executor
    await px.k8s_client.refresh_state_from_k8s()
    await px.docker_client.refresh_state_from_docker_repo()
    return dep


@pytest.fixture(scope="session")
def event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    """Increase the scope of the event loop to the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def app(
    context_dependency: MockContextDependency,
    obj_factory: TestObjectFactory,
    std_config_dir: Path,
) -> AsyncIterator[FastAPI]:
    """Return a configured test application.

    Wraps the application in a lifespan manager so that startup and shutdown
    events are sent during test execution.
    """
    app = create_app(context_dependency=context_dependency)
    async with LifespanManager(app):
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
async def factory(config: Configuration) -> AsyncIterator[Factory]:
    """Create a component factory for tests."""
    async with Factory.standalone(config) as factory:
        yield factory


def make_request(token: str) -> Request:
    return Request(
        {
            "type": "http",
            "path": "/",
            "headers": Headers({"Authorization": f"Bearer {token}"}).raw,
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "client": {"127.0.0.1", 8080},
            "server": {"127.0.0.1", 8080},
        }
    )


@pytest_asyncio.fixture
async def user_context(context_dependency: MockContextDependency) -> Context:
    return await context_dependency(
        request=make_request(token="token-of-affection"),
    )
