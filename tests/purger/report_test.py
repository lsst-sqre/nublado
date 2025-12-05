"""Test reporting functionality."""

import pytest

from nublado.purger.config import Config
from nublado.purger.exceptions import PlanNotReadyError
from nublado.purger.purger import Purger


@pytest.mark.asyncio
async def test_noplan(purger_config: Config) -> None:
    purger = Purger(config=purger_config)
    with pytest.raises(PlanNotReadyError):
        await purger.report()


@pytest.mark.asyncio
async def test_report(purger_config: Config) -> None:
    purger = Purger(config=purger_config)
    await purger.plan()
    await purger.report()
