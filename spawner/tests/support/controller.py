"""Mock responses from jupyterlab-controller."""

from __future__ import annotations

import respx
from httpx import Request, Response

from rsp_restspawner.constants import LabStatus

__all__ = [
    "MockLabController",
    "register_mock_lab_controller",
]


class MockLabController:
    """Mock Nublado lab controller.

    This is an extremely simplified version of the lab controller API
    specified in `SQR-066 <https://sqr-066.lsst.io/>`__.
    """

    def __init__(self, base_url: str) -> None:
        self._url = f"{base_url}/spawner/v1"
        self._lab_status: dict[str, LabStatus] = {}

    def create(self, request: Request, user: str) -> Response:
        if self._lab_status.get(user):
            return Response(status_code=409)
        self._lab_status[user] = LabStatus.RUNNING
        location = f"{self._url}/{user}"
        return Response(status_code=303, headers={"Location": location})

    def delete(self, request: Request, user: str) -> Response:
        if self._lab_status.get(user):
            del self._lab_status[user]
            return Response(status_code=202)
        else:
            return Response(status_code=404)

    def set_status(self, user: str, status: LabStatus) -> None:
        """Set the lab status for a given user, called by tests."""
        self._lab_status[user] = status

    def status(self, request: Request, user: str) -> Response:
        if not self._lab_status.get(user):
            return Response(status_code=404)
        return Response(
            status_code=200,
            json={
                "status": self._lab_status[user],
                "internal_url": f"http://lab.nublado-{user}:8888",
            },
        )


def register_mock_lab_controller(
    respx_mock: respx.Router, base_url: str
) -> MockLabController:
    """Mock out a Nublado lab controller.

    Parameters
    ----------
    respx_mock
        Mock router.
    base_url
        Base URL for the lab controller.

    Returns
    -------
    MockLabController
        The mock JupyterlabController object.
    """
    labs_url = f"{base_url}/spawner/v1/labs/(?P<user>[^/]*)"
    create_url = f"{labs_url}/create"

    mock = MockLabController(base_url)
    respx_mock.get(url__regex=labs_url).mock(side_effect=mock.status)
    respx_mock.delete(url__regex=labs_url).mock(side_effect=mock.delete)
    respx_mock.post(url__regex=create_url).mock(side_effect=mock.create)
    return mock
