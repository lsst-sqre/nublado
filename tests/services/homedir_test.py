"""Test for the alternate homedir schema."""

from __future__ import annotations

import pytest

from jupyterlabcontroller.factory import Factory

from ..settings import TestObjectFactory
from ..support.config import configure
from ..support.data import read_output_data


@pytest.mark.asyncio
async def test_homedir_schema_nss(obj_factory: TestObjectFactory) -> None:
    """Test building a passwd file with the alternate homedir layout."""
    _, user = obj_factory.get_user()
    config = configure("homedir-schema")
    expected_nss = read_output_data("homedir-schema", "nss.json")

    async with Factory.standalone(config) as factory:
        lm = factory.create_lab_manager()
        nss = lm.build_nss(user)
        assert nss == expected_nss
