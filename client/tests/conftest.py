"""Text fixtures for Nublado client tests."""

from base64 import urlsafe_b64encode
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
import respx
import safir.logging
import structlog
from rubin.repertoire import (
    Discovery,
    DiscoveryClient,
    register_mock_discovery,
)
from structlog.stdlib import BoundLogger

from rubin.nublado.client import (
    MockJupyter,
    NubladoClient,
    register_mock_jupyter,
)


@pytest.fixture
def configured_logger() -> BoundLogger:
    safir.logging.configure_logging(
        name="nublado-client",
        profile=safir.logging.Profile.development,
        log_level=safir.logging.LogLevel.DEBUG,
    )
    return structlog.get_logger("nublado-client")


def _create_mock_token(username: str, token: str) -> str:
    # A mock token is: "gt-<base-64 encoded username>.<base64 encoded token>"
    # That is then decoded to extract the username in the Jupyter mock.
    enc_u = urlsafe_b64encode(username.encode()).decode()
    enc_t = urlsafe_b64encode(token.encode()).decode()
    return f"gt-{enc_u}.{enc_t}"


@pytest_asyncio.fixture
async def mock_jupyter(
    respx_mock: respx.Router, username: str, token: str
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
def configured_client(
    configured_logger: BoundLogger,
    username: str,
    token: str,
    mock_jupyter: MockJupyter,
) -> NubladoClient:
    return NubladoClient(
        username=username,
        token=token,
        logger=configured_logger,
    )


@pytest.fixture(autouse=True, params=["single", "subdomain"])
def mock_discovery(
    respx_mock: respx.Router,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> Discovery:
    monkeypatch.setenv("REPERTOIRE_BASE_URL", "https://example.com/repertoire")
    filename = f"{request.param}.json"
    path = Path(__file__).parent / "data" / "discovery" / filename
    return register_mock_discovery(respx_mock, path)


@pytest.fixture
def token(username: str) -> str:
    return _create_mock_token(username, "token-of-authority")


@pytest.fixture
def username() -> str:
    return "rachel"
