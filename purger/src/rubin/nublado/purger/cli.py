"""CLI for the filesystem purger."""

import argparse
import asyncio
import os
from pathlib import Path

from safir.datetime import parse_timedelta

from rubin.nublado.purger.constants import CONFIG_FILE_ENV_VAR

from .config import Config
from .purger import Purger


def _add_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument(
        "-c",
        "--config-file",
        "--config",
        type=Path,
        help="Application configuration file",
    )
    parser.add_argument(
        "-p",
        "--policy-file",
        "--policy",
        type=Path,
        help="Purger policy configuration file",
    )
    parser.add_argument(
        "-d", "--debug", action="store_true", help="Enable debug logging"
    )
    parser.add_argument(
        "-x",
        "--dry-run",
        action="store_true",
        help="Do not act, but report what would be done",
    )

    return parser


def _add_future_time(
    parser: argparse.ArgumentParser,
) -> argparse.ArgumentParser:
    parser.add_argument(
        "-t",
        "--future_duration",
        "--time",
        "--future-time",
        type=parse_timedelta,
        help="Duration from now to future time to build a plan for",
    )

    return parser


def _postprocess_args_to_config(raw_args: argparse.Namespace) -> Config:
    if env_config_path := os.getenv(CONFIG_FILE_ENV_VAR):
        config_file = Path(env_config_path)
    else:
        config_file = raw_args.config_file

    config = Config.from_file(config_file)
    config.policy_file = raw_args.policy_file or config.policy_file

    # For dry-run and debug, if specified, use that, and if not, do whatever
    # the config says.
    config.debug = raw_args.debug or config.debug
    config.configure_logging()
    config.dry_run = raw_args.dry_run or config.dry_run

    # Add the time-into-the-future (used for warning only)
    if future_duration := getattr(raw_args, "future_duration", None):
        config.future_duration = future_duration
    return config


def _get_executor(desc: str) -> Purger:
    parser = argparse.ArgumentParser(description=desc)
    parser = _add_args(parser)
    args = parser.parse_args()
    config = _postprocess_args_to_config(args)
    return Purger(config=config)


def _get_warner(desc: str) -> Purger:
    parser = argparse.ArgumentParser(description=desc)
    parser = _add_args(parser)
    parser = _add_future_time(parser)
    args = parser.parse_args()
    config = _postprocess_args_to_config(args)
    return Purger(config=config)


def report() -> None:
    """Report what files would be purged."""
    reporter = _get_executor("Report what files would be purged.")
    asyncio.run(reporter.plan())
    asyncio.run(reporter.report())


def purge() -> None:
    """Purge files."""
    purger = _get_executor("Purge files.")
    asyncio.run(purger.plan())
    asyncio.run(purger.purge())


def execute() -> None:
    """Make a plan, report, and purge files."""
    purger = _get_executor("Report and purge files.")
    asyncio.run(purger.execute())


def warn() -> None:
    """Make a plan for some time in the future, and report as if it were
    that time.
    """
    warner = _get_warner("Make a plan for a future time and report it.")
    asyncio.run(warner.plan())
    asyncio.run(warner.report())
