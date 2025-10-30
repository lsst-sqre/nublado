"""Text fixtures for Nublado client tests."""

from base64 import urlsafe_b64encode
from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
import pytest_asyncio
import respx
import safir.logging
import structlog
import websockets
from rubin.repertoire import (
    Discovery,
    DiscoveryClient,
    register_mock_discovery,
)
from structlog.stdlib import BoundLogger

from rubin.nublado.client import (
    MockJupyter,
    MockJupyterWebSocket,
    NubladoClient,
    mock_jupyter,
    mock_jupyter_websocket,
)


@pytest.fixture
def test_filesystem() -> Iterator[Path]:
    with TemporaryDirectory() as td:
        nb = Path(__file__).parent / "support" / "hello.ipynb"
        contents = nb.read_text()
        o_nb = Path(td) / "hello.ipynb"
        o_nb.write_text(contents)
        nb = Path(__file__).parent / "support" / "faux-input-nb"
        contents = nb.read_text()
        o_nb = Path(td) / "faux-input.ipynb"
        o_nb.write_text(contents)

        yield Path(td)


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
async def jupyter(
    respx_mock: respx.Router,
    username: str,
    token: str,
    test_filesystem: Path,
) -> AsyncGenerator[MockJupyter]:
    """Mock out JupyterHub and Jupyter labs.

    Sets subdomain mode in the mock based on whether the hostname of the
    Nublado URL in service discovery starts with ``nb.``. This allows
    switching to subdomain mode by parameterizing the ``mock_discovery``
    fixture.
    """
    discovery_client = DiscoveryClient()
    base_url = await discovery_client.url_for_ui("nublado")
    assert base_url
    jupyter_mock = mock_jupyter(
        respx_mock,
        base_url=base_url,
        user_dir=test_filesystem,
        use_subdomains="//nb." in base_url,
    )

    # respx has no mechanism to mock aconnect_ws, so we have to do it
    # ourselves.
    @asynccontextmanager
    async def mock_connect(
        url: str,
        additional_headers: dict[str, str],
        max_size: int | None,
        open_timeout: int,
    ) -> AsyncIterator[MockJupyterWebSocket]:
        yield mock_jupyter_websocket(url, additional_headers, jupyter_mock)

    with patch.object(websockets, "connect") as mock:
        mock.side_effect = mock_connect
        yield jupyter_mock


@pytest.fixture
def configured_client(
    configured_logger: BoundLogger,
    username: str,
    token: str,
    test_filesystem: Path,
    jupyter: MockJupyter,
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
