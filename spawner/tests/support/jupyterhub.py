from dataclasses import dataclass


@dataclass
class MockUser:
    name: str
    auth_state: dict[str, str]
    url: str

    async def get_auth_state(self) -> dict[str, str]:
        return self.auth_state


@dataclass
class MockHub:
    api_url: str
    base_url: str
    public_host: str
