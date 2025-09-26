"""Test reporting functionality."""

import pytest

from rubin.nublado.purger.config import Config
from rubin.nublado.purger.exceptions import PlanNotReadyError
from rubin.nublado.purger.purger import Purger


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
