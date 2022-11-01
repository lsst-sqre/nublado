"""Test fixtures for jupyterlab-controller tests."""

from __future__ import annotations

from os.path import dirname
from typing import AsyncIterator
from unittest.mock import patch

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import AsyncClient

from jupyterlabcontroller import main
from jupyterlabcontroller.models.v1.domain.config import Config
from jupyterlabcontroller.storage.prepuller import PrepullerClient

from .settings import (
    TestDependencyFactory,
    TestObjectFactory,
    config_config,
    test_object_factory,
)

_here = dirname(__file__)

STDCONFDIR = f"{_here}/configs/standard"


@pytest.fixture
def obj_factory() -> TestObjectFactory:
    return test_object_factory


@pytest.fixture
def config() -> Config:
    return config_config(config_path=STDCONFDIR)


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


@pytest_asyncio.fixture
async def dep_factory(
    config: Config, client: AsyncClient
) -> TestDependencyFactory:
    """Return a ``TestDependencyFactory`` configured to supply dependencies."""
    return TestDependencyFactory.initialize(config=config, httpx_client=client)


@pytest_asyncio.fixture
async def prepuller_dep(
    app: FastAPI,
    obj_factory: TestObjectFactory,
    dep_factory: TestDependencyFactory,
) -> PrepullerClient:
    """Return a ``PrepullerClient`` configured to mock the K8s call."""
    pc = dep_factory.prepuller_client
    patch.object(
        pc, "get_image_data_from_k8s", return_value=obj_factory.nodecontents
    )
    return pc
