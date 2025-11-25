"""Tests for the ``GafaelfawrUserInfo`` model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from controller.models.domain.gafaelfawr import UserGroup

from ...support.data import read_input_users_json


def test_no_name() -> None:
    users = read_input_users_json("no-name", "users")
    assert users["token-of-anonymity"].name is None


def test_bad_groupname() -> None:
    with pytest.raises(ValidationError):
        _ = UserGroup(name="-this-won't-work", id=2025)


def test_letter_dash_numeric_groupname() -> None:
    _ = UserGroup(
        name="G-827698",
        id=2025,
    )
