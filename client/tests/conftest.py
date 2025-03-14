"""Text fixtures for Nublado client tests."""

from base64 import urlsafe_b64encode
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
import respx
import safir.logging
import structlog
import websockets
from structlog.stdlib import BoundLogger

from rubin.nublado.client import NubladoClient
from rubin.nublado.client.models import User
from rubin.nublado.client.testing import (
    MockJupyter,
    MockJupyterWebSocket,
    mock_jupyter,
    mock_jupyter_websocket,
)


@pytest.fixture
def environment_url() -> str:
    return "https://data.example.org"


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


@pytest.fixture
def test_user() -> User:
    username = "rachel"
    token = "token-of-authority"
    mock_token = _create_mock_token(username, token)
    return User(username=username, token=mock_token)


@pytest.fixture(ids=["shared", "subdomain"], params=[False, True])
def jupyter(
    respx_mock: respx.Router,
    environment_url: str,
    test_filesystem: Path,
    request: pytest.FixtureRequest,
) -> Iterator[MockJupyter]:
    """Mock out JupyterHub and Jupyter labs."""
    jupyter_mock = mock_jupyter(
        respx_mock,
        base_url=environment_url,
        user_dir=test_filesystem,
        use_subdomains=request.param,
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
    environment_url: str,
    configured_logger: BoundLogger,
    test_user: User,
    test_filesystem: Path,
    jupyter: MockJupyter,
) -> NubladoClient:
    client = NubladoClient(
        user=test_user, logger=configured_logger, base_url=environment_url
    )
    # For the test client, we also have to add the two headers that would
    # be added by a GafaelfawrIngress in real life.
    client._client.headers["X-Auth-Request-User"] = test_user.username
    client._client.headers["X-Auth-Request-Token"] = test_user.token
    return client
