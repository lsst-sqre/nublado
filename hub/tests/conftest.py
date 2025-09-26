"""Fixtures for tests of the Nublado custom spawner class."""

from __future__ import annotations

from pathlib import Path

import pytest
import respx

from rubin.nublado.spawner import NubladoSpawner

from .support.controller import MockLabController, register_mock_lab_controller
from .support.jupyterhub import MockHub, MockUser


@pytest.fixture
def mock_lab_controller(respx_mock: respx.Router) -> MockLabController:
    url = "https://rsp.example.org/nublado"
    admin_token = (Path(__file__).parent / "data" / "admin-token").read_text()
    return register_mock_lab_controller(
        respx_mock,
        url,
        user_token="token-of-affection",
        admin_token=admin_token.strip(),
    )


@pytest.fixture
def spawner(mock_lab_controller: MockLabController) -> NubladoSpawner:
    """Add spawner state that normally comes from JupyterHub."""
    result = NubladoSpawner()
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
