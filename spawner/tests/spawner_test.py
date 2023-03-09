import pytest
import respx

from rsp_restspawner.spawner import RSPRestSpawner

from .support.controller import (
    MockJupyterLabController,
    register_mock_controller,
)

base_url = "https://rsp.example.org"
app_route = "nublado"
user = "rachel"


@pytest.mark.asyncio
@pytest.mark.respx(assert_all_called=False)
async def test_start(
    respx_mock: respx.Router, restspawner_mock: RSPRestSpawner
) -> None:
    ctrl = register_mock_controller(
        respx_mock, base_url=base_url, app_route=app_route, user=user
    )
    assert type(ctrl) is MockJupyterLabController
    # After getting either a 303 or 409, we try the user-status route
    # and should get the value of the internal URL for the Lab
    r = await restspawner_mock.start()  # gives 303
    assert r == f"http://lab.{app_route}-{user}:8888"
    r = await restspawner_mock.start()  # gives 409
    assert r == f"http://lab.{app_route}-{user}:8888"


@pytest.mark.asyncio
@pytest.mark.respx(assert_all_called=False)
async def test_stop(
    respx_mock: respx.Router, restspawner_mock: RSPRestSpawner
) -> None:
    ctrl = register_mock_controller(
        respx_mock, base_url=base_url, app_route=app_route, user=user
    )
    assert type(ctrl) is MockJupyterLabController
    # Generates a 202
    await restspawner_mock.stop()
    # Generates a 404
    await restspawner_mock.stop()


@pytest.mark.asyncio
@pytest.mark.respx(assert_all_called=False)
async def test_poll(
    respx_mock: respx.Router, restspawner_mock: RSPRestSpawner
) -> None:
    ctrl = register_mock_controller(
        respx_mock, base_url=base_url, app_route=app_route, user=user
    )
    r = await restspawner_mock.poll()
    assert r == 0
    await restspawner_mock.start()
    r = await restspawner_mock.poll()
    assert r is None
    ctrl.add_or_update_user(user, False)
    r = await restspawner_mock.poll()
    assert r == 1
    await restspawner_mock.stop()
    r = await restspawner_mock.poll()
    assert r == 0


# Unfortunately, without simulating a lot more of the JupyterHub API,
# and starting a whole JupyterHub app, not just the spawner class, I don't
# know how to exercise the progress bar/progress() method.
