"""Fixtures for tests of the Nublado custom spawner class."""

from pathlib import Path

import pytest
import pytest_asyncio
import respx
from rubin.repertoire import DiscoveryClient, register_mock_discovery
from safir.testing.data import Data

from rubin.nublado.spawner import NubladoSpawner

from .support.controller import MockLabController, register_mock_lab_controller
from .support.jupyterhub import MockHub, MockUser


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-test-data",
        action="store_true",
        default=False,
        help="Overwrite expected test output with current results",
    )


@pytest.fixture
def data(request: pytest.FixtureRequest) -> Data:
    update = request.config.getoption("--update-test-data")
    return Data(Path(__file__).parent / "data", update_test_data=update)


@pytest.fixture
def discovery_url(data: Data, respx_mock: respx.Router) -> str:
    path = data.path("discovery.json")
    base_url = "https://example.com/repertoire"
    register_mock_discovery(respx_mock, path, base_url)
    return base_url


@pytest_asyncio.fixture
async def mock_lab_controller(
    data: Data, discovery_url: str, respx_mock: respx.Router
) -> MockLabController:
    discovery = DiscoveryClient(base_url=discovery_url)
    nublado_url = await discovery.url_for_internal("nublado-controller")
    assert nublado_url
    return register_mock_lab_controller(
        respx_mock,
        nublado_url,
        user_token="token-of-affection",
        admin_token=data.read_text("admin-token", strip=True),
    )


@pytest.fixture
def spawner(
    data: Data, discovery_url: str, mock_lab_controller: MockLabController
) -> NubladoSpawner:
    """Add spawner state that normally comes from JupyterHub."""
    result = NubladoSpawner(
        admin_token_path=str(data.path("admin-token")),
        repertoire_base_url=discovery_url,
    )
    result.hub = MockHub()
    result.user = MockUser(
        name="rachel",
        auth_state={"token": "token-of-affection"},
        url="http://lab.nublado-rachel:8888",
    )
    return result
