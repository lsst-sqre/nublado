"""Mock responses from jupyterlab-controller."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Optional

import respx
from httpx import AsyncByteStream, Request, Response

from rsp_restspawner.spawner import LabStatus

__all__ = [
    "MockLabController",
    "register_mock_lab_controller",
]


class MockProgress(AsyncByteStream):
    """Generator that produces progress events for a lab spawn.

    An instantiation of this object is suitable for passing as the stream
    argument to an `httpx.Response`.

    Parameters
    ----------
    user
        Name of user for which progress events should be generated.
    delay
        Delay by this long between events.
    """

    def __init__(self, user: str, delay: Optional[timedelta] = None) -> None:
        self._user = user
        self._delay = delay if delay else timedelta(seconds=0)

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"event: progress\r\n"
        yield b"data: 2\r\n"
        yield b"\r\n"
        yield b"event: info\r\n"
        yield b"data: Lab creation initiated\r\n"
        yield b"\r\n"

        await asyncio.sleep(self._delay.total_seconds())

        yield b"event: progress\r\n"
        yield b"data: 45\r\n"
        yield b"\r\n"
        yield b"event: info\r\n"
        yield b"data: Pod requested\r\n"
        yield b"\r\n"

        await asyncio.sleep(self._delay.total_seconds())

        yield b"event: complete\r\n"
        msg = f"Pod successfully spawned for {self._user}"
        yield b"data: " + msg.encode() + b"\r\n"
        yield b"\r\n"


class MockLabController:
    """Mock Nublado lab controller.

    This is an extremely simplified version of the lab controller API
    specified in `SQR-066 <https://sqr-066.lsst.io/>`__.

    Attributes
    ----------
    base_url
        Base URL with which the mock was configured.

    Parameters
    ----------
    base_url
        Base URL where the mock is installed, used for constructing redirects.
    """

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
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

    def events(self, request: Request, user: str) -> Response:
        if not self._lab_status.get(user):
            return Response(status_code=404)
        stream = MockProgress(user)
        return Response(
            status_code=200,
            headers={"Content-Type": "text/event-stream"},
            stream=stream,
        )

    def lab_form(self, request: Request, user: str) -> Response:
        return Response(
            status_code=200, text=f"<p>This is some lab form for {user}</p>"
        )

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
    base_labs_url = f"{base_url}/spawner/v1/labs/(?P<user>[^/]*)"
    lab_url = f"{base_labs_url}$"
    create_url = f"{base_labs_url}/create$"
    events_url = f"{base_labs_url}/events$"
    lab_form_url = f"{base_url}/spawner/v1/lab-form/(?P<user>[^/]*)$"

    mock = MockLabController(base_url)
    respx_mock.get(url__regex=lab_url).mock(side_effect=mock.status)
    respx_mock.delete(url__regex=lab_url).mock(side_effect=mock.delete)
    respx_mock.post(url__regex=create_url).mock(side_effect=mock.create)
    respx_mock.get(url__regex=events_url).mock(side_effect=mock.events)
    respx_mock.get(url__regex=lab_form_url).mock(side_effect=mock.lab_form)
    return mock
