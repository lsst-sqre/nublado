import httpx
import pytest
import respx

from rsp_restspawner.spawner import RSPRestSpawner

base_url = "https://rsp.example.org"
user = "rachel"
ctrl_url = f"{base_url}/nublado/spawner/v1"


def mock_routes(
    respx_mock: respx.Router,
    routes: list[str],
    verb: str,
    retval: httpx.Response,
) -> None:
    for rte in routes:
        if verb == "get":
            respx_mock.get(rte).mock(return_value=retval)
        elif verb == "post":
            respx_mock.post(rte).mock(return_value=retval)
        elif verb == "delete":
            respx_mock.delete(rte).mock(return_value=retval)
        else:
            raise RuntimeError(f"Unknown verb {verb}")


@pytest.mark.asyncio
async def test_start(
    respx_mock: respx.Router, restspawner_mock: RSPRestSpawner
) -> None:
    retval = httpx.Response(303, text="f{ctrl_url}/labs/{user}")
    routes = [f"{ctrl_url}/labs/{user}/create"]
    mock_routes(respx_mock, routes, "post", retval)
    routes2 = [f"{ctrl_url}/labs/{user}"]
    retval2 = httpx.Response(
        200,
        json={
            "user": "rachel",
            "status": "running",
            "internal_url": "http://nublado-rachel/nb-rachel:8888",
        },
    )
    mock_routes(respx_mock, routes2, "get", retval2)
    r = await restspawner_mock.start()
    assert r == "http://nublado-rachel/nb-rachel:8888"


@pytest.mark.asyncio
@pytest.mark.respx(base_url=base_url)
async def test_stop(
    respx_mock: respx.Router, restspawner_mock: RSPRestSpawner
) -> None:
    routes = [f"{ctrl_url}/labs/{user}"]
    retval = httpx.Response(202)
    mock_routes(respx_mock, routes, "delete", retval)
    await restspawner_mock.stop()


@pytest.mark.asyncio
@pytest.mark.respx(base_url=base_url)
async def test_poll_running(
    respx_mock: respx.Router, restspawner_mock: RSPRestSpawner
) -> None:
    routes = [f"{ctrl_url}/user-status"]
    retval = httpx.Response(
        200,
        json={
            "user": "rachel",
            "status": "running",
            "internal_url": "http://nublado-rachel/nb-rachel:8888",
        },
    )
    mock_routes(respx_mock, routes, "get", retval)
    r = await restspawner_mock.poll()
    assert r is None


@pytest.mark.asyncio
@pytest.mark.respx(base_url=base_url)
async def test_poll_stopped(
    respx_mock: respx.Router, restspawner_mock: RSPRestSpawner
) -> None:
    routes = [f"{ctrl_url}/user-status"]
    retval = httpx.Response(404)
    mock_routes(respx_mock, routes, "get", retval)
    r = await restspawner_mock.poll()
    assert r == 0


@pytest.mark.asyncio
@pytest.mark.respx(base_url=base_url)
async def test_poll_failed(
    respx_mock: respx.Router, restspawner_mock: RSPRestSpawner
) -> None:
    routes = [f"{ctrl_url}/user-status"]
    retval = httpx.Response(
        200, json={"user": "rachel", "status": "failed", "pod": "missing"}
    )
    mock_routes(respx_mock, routes, "get", retval)
    r = await restspawner_mock.poll()
    assert r == 1


# Unfortunately, without simulating a lot more of the JupyterHub API,
# and starting a whole JupyterHub app, not just the spawner class, I don't
# know how to exercise the progress bar/progress() method.
