"""Text fixtures for Nublado client tests."""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
import respx
import safir.logging
import structlog
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


@pytest.fixture
def test_user() -> User:
    return User(username="rachel", token="token-of-authority")


@pytest.fixture
def jupyter(
    respx_mock: respx.Router,
    environment_url: str,
    test_filesystem: Path,
) -> Iterator[MockJupyter]:
    """Mock out JupyterHub and Jupyter labs."""
    jupyter_mock = mock_jupyter(
        respx_mock,
        base_url=environment_url,
        user_dir=test_filesystem,
    )

    # respx has no mechanism to mock aconnect_ws, so we have to do it
    # ourselves.
    @asynccontextmanager
    async def mock_connect(
        url: str,
        extra_headers: dict[str, str],
        max_size: int | None,
        open_timeout: int,
    ) -> AsyncIterator[MockJupyterWebSocket]:
        yield mock_jupyter_websocket(url, extra_headers, jupyter_mock)

    with patch("rubin.nublado.client.nubladoclient.websocket_connect") as mock:
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
