"""CLI for the filesystem purger."""

import functools
import os
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path

import click
from safir.asyncio import run_with_asyncio
from safir.click import display_help
from safir.datetime import parse_timedelta

from rubin.nublado.purger.constants import (
    CONFIG_FILE,
    CONFIG_FILE_ENV_VAR,
)

from .config import Config
from .purger import Purger


def _common[**P, R](
    func: Callable[P, Awaitable[R]],
) -> Callable[P, R]:
    """Add common Click options and error reporting common a command."""

    @click.option(
        "--debug",
        "-d",
        is_flag=True,
        help="Enable debug logging",
    )
    @click.option(
        "--dry-run",
        "-x",
        is_flag=True,
        help="Do not act, but report what would be done",
    )
    @click.option(
        "--policy-file",
        "-p",
        type=Path,
        help="Purger policy configuration file",
        default=None,
    )
    @click.option(
        "--config-file",
        "-c",
        help="Application configuration file",
        type=Path,
        default=CONFIG_FILE,
    )
    @run_with_asyncio
    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        # Configure slack alerting and report any exceptions
        return await func(*args, **kwargs)

    return wrapper


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(message="%(version)s")
def main() -> None:
    """Nublado file purger command-line interface."""


@main.command()
@click.argument("topic", default=None, required=False, nargs=1)
@click.argument("subtopic", default=None, required=False, nargs=1)
@click.pass_context
def help(ctx: click.Context, topic: str | None, subtopic: str | None) -> None:
    """Show help for any command."""
    display_help(main, ctx, topic, subtopic)


def _make_purger(
    *,
    config_file: Path,
    policy_file: Path | None,
    dry_run: bool,
    debug: bool,
    future_duration: timedelta | None = None,
) -> Purger:
    """Construct a Purger, overriding config from CLI options."""
    # Prefer config file from env var
    if env_config_path := os.getenv(CONFIG_FILE_ENV_VAR):
        config_file = Path(env_config_path)

    config = Config.from_file(config_file)

    if policy_file:
        config.policy_file = policy_file

    # For dry-run and debug, if specified, use that, and if not, do whatever
    # the config says.
    if debug:
        config.debug = debug
        config.configure_logging()

    if dry_run:
        config.dry_run = dry_run

    # Add the time-into-the-future (used for warning only)
    if future_duration:
        config.future_duration = future_duration

    return Purger(config=config)


@main.command
@_common
async def report(
    *,
    config_file: Path,
    policy_file: Path | None,
    dry_run: bool,
    debug: bool,
) -> None:
    """Report what files would be purged."""
    purger = _make_purger(
        config_file=config_file,
        policy_file=policy_file,
        dry_run=dry_run,
        debug=debug,
    )
    await purger.plan()
    await purger.report()


@main.command
@_common
async def execute(
    *,
    config_file: Path,
    policy_file: Path | None,
    dry_run: bool,
    debug: bool,
) -> None:
    """Make a plan, report, and purge files."""
    purger = _make_purger(
        config_file=config_file,
        policy_file=policy_file,
        dry_run=dry_run,
        debug=debug,
    )
    await purger.execute()


@main.command
@click.option(
    "--future-duration",
    "-t",
    type=parse_timedelta,
    help="Duration from now to future time to build a plan for",
    default=None,
)
@_common
async def warn(
    *,
    config_file: Path,
    policy_file: Path | None,
    dry_run: bool,
    debug: bool,
    future_duration: timedelta,
) -> None:
    """Make a plan for some time in the future, and report as if it were
    that time.
    """
    purger = _make_purger(
        config_file=config_file,
        policy_file=policy_file,
        dry_run=dry_run,
        debug=debug,
        future_duration=future_duration,
    )
    await purger.plan()
    await purger.report()
