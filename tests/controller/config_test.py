"""Tests for configuration validators."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nublado.controller.config import LabConfig

from ..support.config import configure
from ..support.data import NubladoData


def test_reserved_env() -> None:
    with pytest.raises(ValidationError):
        LabConfig(env={"ACCESS_TOKEN": "blahblah"}, namespace_prefix="nublado")
    with pytest.raises(ValidationError):
        LabConfig(env={"JUPYTERHUB_FOO": "blah"}, namespace_prefix="nublado")


def test_reserved_paths() -> None:
    with pytest.raises(ValidationError):
        LabConfig(
            files={"/etc/passwd": "some content\n"}, namespace_prefix="nublado"
        )


@pytest.mark.asyncio
async def test_no_home(data: NubladoData) -> None:
    with pytest.raises(ValidationError):
        await configure(data, "no-home")
