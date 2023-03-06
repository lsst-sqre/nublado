import httpx
import pytest
import respx

from rsp_restspawner.spawner import RSPRestSpawner

base_url = "https://rsp.example.org"
user = "rachel"
namespace = "userlabs"
ctrl_url = f"{base_url}/{namespace}/spawner/v1"


@pytest.mark.asyncio
async def test_start(
    respx_mock: respx.Router, restspawner_mock: RSPRestSpawner
) -> None:
    route = f"{ctrl_url}/labs/{user}/create"
    respx_mock.post(route).mock(
        return_value=httpx.Response(303, text="f{ctrl_url}/labs/{user}")
    )
    r = await restspawner_mock.start()
    assert r == f"http://lab.{namespace}-{user}:8888"


@pytest.mark.asyncio
@pytest.mark.respx(base_url=base_url)
async def test_stop(
    respx_mock: respx.Router, restspawner_mock: RSPRestSpawner
) -> None:
    route = f"{ctrl_url}/labs/{user}"
    respx_mock.delete(route).mock(return_value=httpx.Response(202))
    await restspawner_mock.stop()


@pytest.mark.asyncio
@pytest.mark.respx(base_url=base_url)
async def test_poll_running(
    respx_mock: respx.Router, restspawner_mock: RSPRestSpawner
) -> None:
    route = f"{ctrl_url}/user-status"
    respx_mock.get(route).mock(
        return_value=httpx.Response(
            200, json={"user": "rachel", "status": "running"}
        )
    )
    r = await restspawner_mock.poll()
    assert r is None


@pytest.mark.asyncio
@pytest.mark.respx(base_url=base_url)
async def test_poll_stopped(
    respx_mock: respx.Router, restspawner_mock: RSPRestSpawner
) -> None:
    route = f"{ctrl_url}/user-status"
    respx_mock.get(route).mock(return_value=httpx.Response(404))
    r = await restspawner_mock.poll()
    assert r == 1


@pytest.mark.asyncio
@pytest.mark.respx(base_url=base_url)
async def test_poll_failed(
    respx_mock: respx.Router, restspawner_mock: RSPRestSpawner
) -> None:
    route = f"{ctrl_url}/user-status"
    respx_mock.get(route).mock(
        return_value=httpx.Response(
            200, json={"user": "rachel", "status": "failed", "pod": "missing"}
        )
    )
    r = await restspawner_mock.poll()
    assert r == 2


# Unfortunately, without simulating a lot more of the JupyterHub API,
# and starting a whole JupyterHub app, not just the spawner class, I don't
# know how to exercise the progress bar/progress() method.
