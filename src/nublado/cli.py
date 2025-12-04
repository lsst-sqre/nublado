"""Nublado Command-Line Interface."""

from __future__ import annotations

import asyncio
import functools
import os
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path

import click
import uvicorn
from safir.asyncio import run_with_asyncio
from safir.click import display_help
from safir.datetime import current_datetime, isodatetime, parse_timedelta
from safir.sentry import initialize_sentry
from safir.slack.webhook import SlackWebhookClient
from structlog.stdlib import get_logger

from . import __version__
from .constants import (
    ALERT_HOOK_ENV_VAR,
    ROOT_LOGGER,
)
from .inithome.provisioner import Provisioner
from .purger import Purger
from .purger.config import Config as PurgerConfig
from .purger.constants import (
    CONFIG_FILE as PURGER_CONFIG_FILE,
)
from .purger.constants import (
    CONFIG_FILE_ENV_VAR as PURGER_CONFIG_FILE_ENV_VAR,
)
from .startup.services.labrunner import LabRunner
from .startup.services.landing_page.provisioner import (
    Provisioner as LandingPageProvisioner,
)

__all__ = [
    "controller",
    "fsadmin",
    "inithome",
    "landingpage",
    "main",
    "purger",
    "startup",
]


def _purger_common[**P, R](
    async_func: Callable[P, Awaitable[R]],
) -> Callable[P, R]:
    """Add common purger options and error reporting to a command.

    We should probably eventually use a wrapper like this to handle
    Sentry and Slack reporting everywhere, but initially each of the
    subcomponents that do either of those manage it internally.
    """

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
        default=PURGER_CONFIG_FILE,
    )
    @click.option(
        "--debug",
        "-d",
        is_flag=True,
        envvar="DEBUG",
        help="Enable debug logging",
    )
    @run_with_asyncio
    @functools.wraps(async_func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        # Configure slack alerting and report any exceptions
        logger = get_logger(ROOT_LOGGER)
        if alert_hook := os.environ.get(ALERT_HOOK_ENV_VAR):
            slack_client = SlackWebhookClient(
                alert_hook,
                "Nublado",
                logger=logger,
            )
        else:
            slack_client = None

        try:
            return await async_func(*args, **kwargs)
        except Exception as exc:
            if slack_client:
                await slack_client.post_exception(exc)
            raise

    # Also report to Sentry.
    initialize_sentry(release=__version__)

    return wrapper


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(message="%(version)s")
def main() -> None:
    """Command-line interface for nublado."""


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
    if env_config_path := os.getenv(PURGER_CONFIG_FILE_ENV_VAR):
        config_file = Path(env_config_path)

    config = PurgerConfig.from_file(config_file)

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


@main.group()
@_purger_common
async def purger(
    *,
    config_file: Path,
    policy_file: Path | None,
    dry_run: bool,
    debug: bool,
) -> None:
    """Purge files, or plan future purge."""


@purger.command()
@_purger_common
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


@purger.command()
@_purger_common
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


@purger.command()
@click.option(
    "--future-duration",
    "-t",
    type=parse_timedelta,
    help="Duration from now to future time to build a plan for",
    default=None,
)
@_purger_common
async def warn(
    ctx: click.Context,
    /,
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


@main.command()
def controller() -> None:
    """Start Nublado controller."""
    uvicorn.run(
        "nublado.controller.main:create_app", host="0.0.0.0", port=8080
    )


@main.command()
def inithome() -> None:
    """Provision user home directory.


    ``NUBLADO_GID`` must be set.
    """
    logger = get_logger(ROOT_LOGGER)
    try:
        uid = int(os.environ["NUBLADO_UID"])
        gid = int(os.environ["NUBLADO_GID"])
        home = Path(os.environ["NUBLADO_HOME"])
    except (TypeError, KeyError):
        # Something wasn't set.
        errstr = (
            "Environment variables 'NUBLADO_HOME', 'NUBLADO_UID', and"
            " 'NUBLADO_GID' must all be set."
        )
        logger.critical(errstr)
        raise
    except ValueError:
        # One of the ID numbers did not convert.
        errstr = (
            "Environment variables 'NUBLADO_UID' and 'NUBLADO_GID' must"
            " each be set to an integer."
        )
        logger.critical(errstr)
        raise
    provisioner = Provisioner(home, uid, gid)
    asyncio.run(provisioner.provision())


@main.command()
def startup() -> None:
    """Prepare user environment for RSP startup."""
    # All of the settings are in the environment.  The LabRunner only has
    # one public method.
    LabRunner().go()


@main.command()
def landingpage() -> None:
    """Redirect Lab user to specified landing page.

    Environment variable ``NUBLADO_HOME`` must be set.
    """
    # This is set by the controller and will be set for Nublado init
    # containers.
    #
    # We never want to raise an exception here: if this action fails, we still
    # want to start the user lab.  If nothing else went wrong, they
    # just won't get redirected to the landing page (but odds are, if something
    # goes wrong here, something is more generally wrong with the Lab
    # environment).

    logger = get_logger(ROOT_LOGGER)
    if not os.getenv("NUBLADO_HOME"):
        logger.critical("Environment variable NUBLADO_HOME is not set!")
        return
    try:
        provisioner = LandingPageProvisioner.from_env()
        provisioner.go()
    except Exception:
        logger.exception("Landing page provisioner failed")


@main.command()
def fsadmin() -> None:
    """Do nothing but log an occasional heartbeat message.

    An administrative user can `kubectl exec` into the container to
    perform filesystem operations.
    """
    logger = get_logger(ROOT_LOGGER)
    count = 0
    while True:
        count += 1
        logger.info(
            f"Nublado fsadmin heartbeat #{count}:"
            f" {isodatetime(current_datetime())}"
        )
        time.sleep(60)
