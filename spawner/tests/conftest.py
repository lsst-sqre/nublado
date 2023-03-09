import os
from pathlib import Path
from typing import Generator
from unittest import mock

import pytest

import rsp_restspawner

from .support.mock_jupyterhub import MockHub, MockUser


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
def restspawner_mock() -> rsp_restspawner.spawner.RSPRestSpawner:
    r = rsp_restspawner.spawner.RSPRestSpawner()
    r.user = MockUser(
        name="rachel",
        auth_state={"token": "token-of-affection"},
        url="https://rsp.example.org/hub/user/rachel",
    )
    r.hub = MockHub(
        api_url="http://nublado.hub:8081",
        public_host="rsp.example.org",
        base_url=os.getenv("EXTERNAL_INSTANCE_URL") + "/hub",
    )
    return r
