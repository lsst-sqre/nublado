import os
from typing import Generator
from unittest import mock

import pytest

import rsp_restspawner

from .support.mock_jupyterhub import MockHub, MockUser


@pytest.fixture(autouse=True)
def env_mock() -> Generator:
    with mock.patch.dict(
        os.environ,
        {
            "EXTERNAL_INSTANCE_URL": "https://rsp.example.org",
            "ADMIN_TOKEN": "token-of-authority",
        },
    ):
        yield


@pytest.fixture
def restspawner_mock() -> rsp_restspawner.spawner.RSPRestSpawner:
    r = rsp_restspawner.spawner.RSPRestSpawner()
    r.user = MockUser(
        name="rachel", auth_state={"token": "token-of-affection"}
    )
    r.hub = MockHub(api_url="http://nublado.hub:8081")
    return r
