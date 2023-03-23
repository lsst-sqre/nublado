"""Fixtures for tests of the Nublado JupyterHub."""

from __future__ import annotations

from pathlib import Path

import pytest
import respx

from rsp_restspawner.spawner import RSPRestSpawner

from .support.controller import MockLabController, register_mock_lab_controller
from .support.jupyterhub import MockHub, MockUser


@pytest.fixture
def mock_lab_controller(respx_mock: respx.Router) -> MockLabController:
    url = "https://rsp.example.org/nublado"
    return register_mock_lab_controller(respx_mock, url)


@pytest.fixture
def spawner(mock_lab_controller: MockLabController) -> RSPRestSpawner:
    """Add spawner state that normally comes from JupyterHub."""
    result = RSPRestSpawner()
    result.admin_token_path = str(
        Path(__file__).parent / "data" / "admin-token"
    )
    result.controller_url = mock_lab_controller.base_url
    result.hub = MockHub()
    result.user = MockUser(
        name="rachel",
        auth_state={"token": "token-of-affection"},
        url="http://lab.nublado-rachel:8888",
    )
    return result
