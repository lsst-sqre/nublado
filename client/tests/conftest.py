"""Text fixtures for Nublado client tests."""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
import respx
import structlog
from rubin.repertoire import (
    Discovery,
    DiscoveryClient,
    register_mock_discovery,
)
from safir.logging import LogLevel, Profile, configure_logging
from structlog.stdlib import BoundLogger

from rubin.nublado.client import (
    MockJupyter,
    NubladoClient,
    register_mock_jupyter,
)


@pytest.fixture
def client(
    logger: BoundLogger,
    username: str,
    token: str,
    mock_jupyter: MockJupyter,
) -> NubladoClient:
    return NubladoClient(username, token, logger=logger)


@pytest.fixture
def logger() -> BoundLogger:
    configure_logging(
        name="nublado", profile=Profile.development, log_level=LogLevel.DEBUG
    )
    return structlog.get_logger("nublado")


@pytest.fixture(params=["single", "subdomain"])
def mock_discovery(
    respx_mock: respx.Router,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> Discovery:
    monkeypatch.setenv("REPERTOIRE_BASE_URL", "https://example.com/repertoire")
    filename = f"{request.param}.json"
    path = Path(__file__).parent / "data" / "discovery" / filename
    return register_mock_discovery(respx_mock, path)


@pytest_asyncio.fixture
async def mock_jupyter(
    respx_mock: respx.Router, mock_discovery: Discovery
) -> AsyncGenerator[MockJupyter]:
    """Mock out JupyterHub and Jupyter labs.

    Sets subdomain mode in the mock based on whether the hostname of the
    Nublado URL in service discovery starts with ``nb.``. This allows
    switching to subdomain mode by parameterizing the ``mock_discovery``
    fixture.
    """
    discovery_client = DiscoveryClient()
    base_url = await discovery_client.url_for_ui("nublado")
    async with register_mock_jupyter(
        respx_mock, use_subdomains=bool(base_url and "//nb." in base_url)
    ) as mock:
        yield mock


@pytest.fixture
def token(username: str) -> str:
    return MockJupyter.create_mock_token(username)


@pytest.fixture
def username() -> str:
    return "rachel"
