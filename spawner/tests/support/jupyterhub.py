"""Mock objects for data normally provided to the spawner by JupyterHub."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["MockHub", "MockUser"]


@dataclass
class MockHub:
    """The ``hub`` attribute of a spawner.

    These values are used by the parent JupyterHub Spawner class to populate
    the default environment. The values are arbitrary -- they just need to
    exist -- so don't go to any great lengths to make them "correct."
    """

    api_url = "http://hub.nublado:8081"
    public_host = "rsp.example.com"
    base_url = "https://rsp.example.com/nb/hub"


@dataclass
class MockUser:
    """The ``user`` attribute of a spawner.

    This is normally populated by GafaelfawrAuthenticator via the JupyterHub
    code, so ``auth_state`` should be set to whatever that authenticator would
    normally set it to.
    """

    name: str
    auth_state: dict[str, str]
    url: str = "https://rsp.example.com/nb/someuser"

    async def get_auth_state(self) -> dict[str, str]:
        return self.auth_state
