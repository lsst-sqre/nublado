"""Fixtures for tests of the Nublado JupyterHub."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Generator
from unittest import mock

import pytest
import respx

from rsp_restspawner.spawner import RSPRestSpawner

from .support.controller import MockLabController, register_mock_lab_controller
from .support.jupyterhub import MockHub, MockUser


@pytest.fixture(autouse=True)
def env_mock() -> Generator:
    input_files = Path(Path(__file__).parent / "testdata")
    with mock.patch.dict(
        os.environ,
        {
            "EXTERNAL_INSTANCE_URL": "https://rsp.example.org",
            "RESTSPAWNER_ADMIN_TOKEN_FILE": str(
                Path(input_files / "admin-token")
            ),
            "RESTSPAWNER_CONFIG_FILE": str(Path(input_files / "config.yaml")),
        },
    ):
        yield


@pytest.fixture
def mock_lab_controller(respx_mock: respx.Router) -> MockLabController:
    url = "https://rsp.example.org/nublado"
    return register_mock_lab_controller(respx_mock, url)


@pytest.fixture
def spawner(mock_lab_controller: MockLabController) -> RSPRestSpawner:
    """Add spawner state that normally comes from JupyterHub."""
    result = RSPRestSpawner()
    result.user = MockUser(
        name="rachel",
        auth_state={"token": "token-of-affection"},
        url="http://lab.nublado-rachel:8888",
    )
    result.hub = MockHub()
    return result
