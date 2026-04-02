"""Test for Docker Registry models."""

import base64
import json
from pathlib import Path

from nublado.models.docker import DockerCredentials, DockerCredentialStore


def test_credential_store(tmp_path: Path) -> None:
    store = DockerCredentialStore({})
    assert store.get("example.com") is None
    credentials = DockerCredentials(username="foo", password="blahblah")
    store.set("example.com", credentials)
    assert store.get("example.com") == credentials
    assert store.get("foo.example.com") == credentials
    assert store.get("example.org") is None
    other_credentials = DockerCredentials(username="u", password="p")
    store.set("example.org", other_credentials)

    store_path = tmp_path / "credentials.json"
    store.save(store_path)
    with store_path.open("r") as f:
        data = json.load(f)
    assert data == {
        "auths": {
            "example.com": {
                "username": "foo",
                "password": "blahblah",
                "auth": base64.b64encode(b"foo:blahblah").decode(),
            },
            "example.org": {
                "username": "u",
                "password": "p",
                "auth": base64.b64encode(b"u:p").decode(),
            },
        }
    }

    store = DockerCredentialStore.from_path(store_path)
    assert store.get("example.com") == credentials
    assert store.get("foo.example.com") == credentials
    assert store.get("example.org") == other_credentials
