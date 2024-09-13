"""Text fixtures for Nublado client tests."""

import json
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
from rubin.nublado.client.models.user import AuthenticatedUser
from rubin.nublado.client.testing.gafaelfawr import (
    GafaelfawrUser,
    GafaelfawrUserInfo,
    MockGafaelfawr,
    register_mock_gafaelfawr,
)
from rubin.nublado.client.testing.jupyter import (
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
def mock_gafaelfawr(
    respx_mock: respx.Router, environment_url: str
) -> MockGafaelfawr:
    user_objs = json.loads(
        (Path(__file__).parent / "support" / "users.json").read_text()
    )
    users = {
        t: GafaelfawrUserInfo.model_validate(u) for t, u in user_objs.items()
    }

    return register_mock_gafaelfawr(
        respx_mock,
        environment_url,
        users,
    )


@pytest.fixture
def test_gafaelfawr_user(mock_gafaelfawr: MockGafaelfawr) -> GafaelfawrUser:
    return mock_gafaelfawr.get_test_token_and_user()


@pytest.fixture
def test_user(
    test_gafaelfawr_user: GafaelfawrUser, mock_gafaelfawr: MockGafaelfawr
) -> AuthenticatedUser:
    scoped_token = mock_gafaelfawr.get_token_info(test_gafaelfawr_user.token)
    return AuthenticatedUser(
        username=test_gafaelfawr_user.username,
        uidnumber=test_gafaelfawr_user.uid,
        gidnumber=test_gafaelfawr_user.gid,
        scopes=scoped_token.scopes,
        token=scoped_token.token,
    )


@pytest.fixture
def jupyter(
    respx_mock: respx.Router,
    environment_url: str,
    mock_gafaelfawr: MockGafaelfawr,
    test_filesystem: Path,
) -> Iterator[MockJupyter]:
    """Mock out JupyterHub and Jupyter labs."""
    jupyter_mock = mock_jupyter(
        respx_mock,
        mock_gafaelfawr=mock_gafaelfawr,
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
    test_user: AuthenticatedUser,
    test_filesystem: Path,
    jupyter: MockJupyter,
) -> NubladoClient:
    return NubladoClient(
        user=test_user, logger=configured_logger, base_url=environment_url
    )
