import os
import urllib
from pathlib import Path
from typing import Generator
from unittest import mock

import pytest

import rsp_restspawner

from .support.jupyterhub import MockHub, MockUser


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
    username = "rachel"
    external_url = rsp_restspawner.util.get_external_instance_url()
    hub_route = rsp_restspawner.util.get_hub_route()
    hostname = urllib.parse.urlparse(external_url).hostname
    assert type(hostname) is str
    r.user = MockUser(
        name=username,
        auth_state={"token": "token-of-affection"},
        url=(external_url + hub_route + f"/hub/user/{username}"),
    )
    r.hub = MockHub(
        api_url=("f{rsp_restspawner.util.get_namespace()}" + ".hub:8081"),
        public_host=hostname,
        base_url=external_url + hub_route + "/hub",
    )
    return r
