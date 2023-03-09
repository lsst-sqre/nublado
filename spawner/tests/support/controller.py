"""Mock responses from jupyterlab-controller."""

from __future__ import annotations

import pytest
import respx
from httpx import Request, Response

import rsp_restspawner


class MockJupyterLabController:
    """Mock JupyterLab Controller that returns what we would expect to
    see when we contact it for start/stop/poll information.

    This is an extremely simplified version of the controller specified at
    https://sqr-066.lsst.io"""

    def __init__(self, base_url: str, app_route: str) -> None:
        self._url = f"{base_url}/{app_route}/spawner/v1"
        # The value True for a user means the simulated Lab is running
        # correctly; False means it is in a failed state.  This is used
        # in poll
        self._users: dict[str, bool] = dict()

    def add_or_update_user(self, user: str, running: bool = True) -> None:
        self._users[user] = running

    def del_user(self, user: str) -> None:
        if user in self._users:
            del self._users[user]

    def create(self, req: Request) -> Response:
        """Mock user creation.  Returns a 409 if the user already
        exists, 303 if not."""
        user = req.url.path.split("/")[-2]  # Post to .../username/create
        if user in self._users:
            return Response(status_code=409)
        self.add_or_update_user(user)
        return Response(
            status_code=303, headers={"Location": self._url + f"/{user}"}
        )

    def delete(self, req: Request) -> Response:
        """Mock user deletion.  Returns a 202 if the user exists and was
        deleted, or a 404 if the user did not exist."""
        user = req.url.path.split("/")[-1]  # it's a delete to .../username
        if user in self._users:
            self.del_user(user)
            return Response(status_code=202)
        return Response(status_code=404)

    def status(self, req: Request) -> Response:
        """Mock user status check.  Returns a 200 if the user exists, and
        a 404 if it does not.

        For a 200, it will return an "application/json" document, with
        a "status" field.  This will be set to "running" if the user is
        healthy, and "failed" otherwise (by way of named constants).

        This is vastly simplified from what the actual controller will
        return.
        """
        user = req.url.path.split("/")[-1]  # it's a get to .../username
        if user in self._users:
            status = rsp_restspawner.constants.LabStatus.RUNNING.value
            if not self._users[user]:
                status = rsp_restspawner.constants.LabStatus.FAILED.value
            return Response(
                status_code=200,
                headers={"Content-Type": "application/json"},
                json={
                    "status": status,
                    "internal_url": (
                        "http://lab."
                        + rsp_restspawner.util.get_application_namespace()
                        + f"-{user}:8888"
                    ),
                },
            )
        return Response(status_code=404)


@pytest.mark.respx(assert_all_called=False)
def register_mock_controller(
    respx_mock: respx.Router, *, base_url: str, app_route: str, user: str
) -> MockJupyterLabController:
    """Mock out a JupyterLab Controller.

    Parameters
    ----------
    respx_mock
        Mock router.
    base_url
        URL of the RSP instance base
    app_route
        Route to the JupyterLab Controller relative to base_url
    user
        User to use with the mock controller

    Returns
    -------
    MockJupyterLabController
        The mock JupyterlabController object.
    """

    ctrl_url = f"{base_url}/{app_route}/spawner/v1"
    create_url = f"{ctrl_url}/labs/{user}/create"
    delete_url = f"{ctrl_url}/labs/{user}"
    status_url = delete_url

    ctrl = MockJupyterLabController(base_url=base_url, app_route=app_route)
    respx_mock.get(status_url).mock(side_effect=ctrl.status)
    respx_mock.delete(delete_url).mock(side_effect=ctrl.delete)
    respx_mock.post(create_url).mock(side_effect=ctrl.create)
    return ctrl
