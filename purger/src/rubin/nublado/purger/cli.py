"""CLI for the filesystem purger."""

import argparse
import asyncio
import os
from pathlib import Path

import yaml
from pydantic import HttpUrl, ValidationError
from safir.datetime import parse_timedelta
from safir.logging import LogLevel, Profile

from .config import Config
from .constants import CONFIG_FILE, ENV_PREFIX
from .models.v1.policy import Policy
from .purger import Purger


def _add_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument(
        "-c",
        "--config-file",
        "--config",
        help="Application configuration file",
    )
    parser.add_argument(
        "-p",
        "--policy-file",
        "--policy",
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
        help="Duration from now to future time to build a plan for",
    )

    return parser


def _postprocess_args_to_config(raw_args: argparse.Namespace) -> Config:
    config: Config | None = None
    override_cf = raw_args.config_file or os.getenv(
        ENV_PREFIX + "CONFIG_FILE", ""
    )
    config_file = Path(override_cf) if override_cf else Path(CONFIG_FILE)
    try:
        config_obj = yaml.safe_load(config_file.read_text())
        config = Config.model_validate(config_obj)
    except (FileNotFoundError, UnicodeDecodeError, ValidationError) as exc:
        # If the file is not there, or readable, or parseable, just
        # start with an empty config and add our command-line options.
        #
        # But also complain.  We don't have a logger yet, so shout to stdout
        # instead.
        print(f"Could not load config '{config_file!s}': {exc}")  # noqa:T201
        config = Config()
    # Validate policy.  If the file is specified, use that; if not, use
    # defaults from config.
    override_pf = raw_args.policy_file or os.getenv(
        ENV_PREFIX + "POLICY_FILE", ""
    )
    policy_file = Path(override_pf) if override_pf else config.policy_file
    policy_obj = yaml.safe_load(policy_file.read_text())
    Policy.model_validate(policy_obj)
    # If we get this far, it's a legal policy file.
    config.policy_file = policy_file

    # For dry-run and debug, if specified, use that, and if not, do whatever
    # the config says.
    override_debug = raw_args.debug or bool(
        os.getenv(ENV_PREFIX + "DEBUG", "")
    )
    if override_debug:
        config.logging.log_level = LogLevel.DEBUG
        config.logging.profile = Profile.development
    override_dry_run = raw_args.dry_run or bool(
        os.getenv(ENV_PREFIX + "DRY_RUN", None)
    )
    if override_dry_run:
        config.dry_run = True

    # Add the time-into-the-future (used for warning only)
    override_future_duration = (
        "future_duration" in raw_args and raw_args.future_duration
    ) or os.getenv(ENV_PREFIX + "FUTURE_DURATION", None)
    if override_future_duration:
        later = parse_timedelta(override_future_duration)
        if later:
            config.future_duration = later

    # Add the Slack alert hook, if we have it.  We should not set this in the
    # config YAML, or the command line, because it's a secret.
    # It ends up getting injected into the environment (which isn't much
    # better) via a K8s secret.
    hook = os.getenv(ENV_PREFIX + "ALERT_HOOK", "")
    if hook:
        config.alert_hook = HttpUrl(url=hook)
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
