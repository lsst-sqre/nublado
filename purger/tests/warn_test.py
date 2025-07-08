"""Test reporting functionality."""

import pytest
from rubin.nublado.purger.config import Config
from rubin.nublado.purger.purger import Purger
from safir.datetime import parse_timedelta
from safir.logging import LogLevel


@pytest.mark.asyncio
async def test_warn(purger_config: Config) -> None:
    purger_config.future_duration = parse_timedelta("3650d")
    purger = Purger(config=purger_config)
    await purger.plan()
    await purger.report()


@pytest.mark.asyncio
async def test_file_count(purger_config: Config) -> None:
    purger_config.future_duration = parse_timedelta("3650d")
    purger_config.logging.log_level = LogLevel.DEBUG
    purger = Purger(config=purger_config)
    await purger.plan()
    assert purger._plan is not None
    victims = purger._plan.files
    # We expect that medium and small in `foobar` will not be marked, since
    # they have intervals of 0.
    assert len(victims) == 4
