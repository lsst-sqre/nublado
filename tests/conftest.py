"""Test fixtures for jupyterlab-controller tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator, Iterator

import pytest
import pytest_asyncio
import structlog
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import AsyncClient
from safir import logging
from safir.dependencies.http_client import http_client_dependency
from structlog.stdlib import BoundLogger

from jupyterlabcontroller.config import Configuration
from jupyterlabcontroller.dependencies.config import configuration_dependency
from jupyterlabcontroller.factory import Factory
from jupyterlabcontroller.main import create_app
from jupyterlabcontroller.models.context import Context
from jupyterlabcontroller.models.domain.docker import DockerCredentialsMap
from jupyterlabcontroller.models.v1.lab import UserInfo

from .settings import TestObjectFactory, test_object_factory
from .support.mockcontext import MockContext

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
def obj_factory() -> TestObjectFactory:
    filename = str(CONFIG_DIR / "test_objects.json")
    test_object_factory.initialize_from_file(filename)
    return test_object_factory


@pytest.fixture
def config() -> Configuration:
    configuration_dependency.set_filename(f"{CONFIG_DIR}/config.yaml")
    return configuration_dependency.config


@pytest.fixture
def logger() -> BoundLogger:
    return structlog.get_logger(logging.logger_name)


@pytest_asyncio.fixture
async def docker_credentials(logger: BoundLogger) -> DockerCredentialsMap:
    filename = str(CONFIG_DIR / "docker_config.json")
    docker_creds = DockerCredentialsMap(filename=filename, logger=logger)
    return docker_creds


@pytest.fixture(scope="session")
def event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    """Increase the scope of the event loop to the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def app() -> AsyncIterator[FastAPI]:
    """Return a configured test application.

    Wraps the application in a lifespan manager so that startup and shutdown
    events are sent during test execution.
    """
    app = create_app(
        config_dir=str(CONFIG_DIR),
    )
    async with LifespanManager(app):
        yield app


@pytest_asyncio.fixture
async def app_client(
    app: FastAPI, config: Configuration
) -> AsyncIterator[AsyncClient]:
    """Return an ``httpx.AsyncClient`` configured to talk to the test app."""
    async with AsyncClient(
        app=app, base_url=config.runtime.instance_url
    ) as client:
        yield client


@pytest_asyncio.fixture
async def context(
    config: Configuration,
    obj_factory: TestObjectFactory,
    logger: BoundLogger,
    factory: Factory,
    token: str,
) -> Context:
    """Return a ``Context`` configured to supply dependencies."""
    cc = MockContext(
        test_obj=obj_factory,
        http_client=await http_client_dependency(),
        logger=logger,
        token=token,
        config=config,
        factory=factory,
    )

    return cc


@pytest_asyncio.fixture
async def user(obj_factory: TestObjectFactory) -> UserInfo:
    return obj_factory.userinfos[0]


@pytest_asyncio.fixture
async def username(user: UserInfo) -> str:
    return user.username


@pytest_asyncio.fixture
async def user_token() -> str:
    return "token-of-affection"


@pytest_asyncio.fixture
async def admin_token() -> str:
    return "token-of-authority"
