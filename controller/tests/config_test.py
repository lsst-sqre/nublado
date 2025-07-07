"""Tests for configuration validators."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from controller.config import LabConfig, LabSizeDefinition
from controller.models.v1.lab import LabSize


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


def test_lab_size_options() -> None:
    # Standard
    lsd = LabSizeDefinition(size=LabSize.MEDIUM, cpu=1.0, memory="4096MiB")
    res = lsd.to_lab_resources()
    assert res.requests.cpu == 0.25
    assert res.requests.memory == 1024 * 1024 * 1024

    # Pin request to limit
    lsd = LabSizeDefinition(
        size=LabSize.MEDIUM,
        cpu=1.0,
        memory="4096MiB",
        limit_to_request_ratio=1.0,
    )
    res = lsd.to_lab_resources()
    assert res.requests.cpu == 1.0
    assert res.requests.memory == 4 * 1024 * 1024 * 1024

    # Request larger than limit, which is an error
    with pytest.raises(ValidationError):
        lsd = LabSizeDefinition(
            size=LabSize.MEDIUM,
            cpu=1.0,
            memory="4096MiB",
            limit_to_request_ratio=0.25,
        )
