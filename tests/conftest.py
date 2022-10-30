"""Test fixtures for jupyterlab-controller tests."""

from __future__ import annotations

from os.path import dirname
from typing import AsyncIterator

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import AsyncClient

from jupyterlabcontroller import main
from jupyterlabcontroller.models.v1.domain.config import Config

from .settings import config_config

_here = dirname(__file__)

STDCONFDIR = f"{_here}/configs/standard"


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
