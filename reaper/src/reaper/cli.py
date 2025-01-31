"""CLI for Registry Reaper."""

import argparse
import code
from pathlib import Path

from .config import Config
from .services.reaper import BuckDharma


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Reap images from container registries."
    )
    parser.add_argument(
        "-c",
        "--config-file",
        "--file",
        type=Path,
        help="reaper config file",
        default=Path("/etc/reaper/config.yaml"),
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Enable debug logging",
        default=False,
    )
    parser.add_argument(
        "-x",
        "--dry-run",
        action="store_true",
        help="Dry run only: do not delete any images",
        default=False,
    )
    parser.add_argument(
        "-s",
        "--skip-tags",
        help=(
            "exclude images with these tags from consideration for"
            " reaping (comma-separated list)"
        ),
        default="",
    )

    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Load config and then drop into Python REPL",
        default=False,
    )
    result = parser.parse_args()
    if result.skip_tags:
        result.skip_tags = set(result.skip_tags.split(","))

    return parser.parse_args()


def _load_config(args: argparse.Namespace) -> Config:
    cfg = Config.from_file(args.config_file)

    # Override settings in config, if dry_run or debug are specified here
    for reg in cfg.registries:
        if args.dry_run:
            reg.dry_run = True
        if args.debug:
            reg.debug = True
    return cfg


def cowbell() -> None:
    """Don't fear the Reaper."""
    args = _parse_args()
    cfg = _load_config(args)

    boc = BuckDharma(cfg)

    if args.interactive:
        print("Reaper application is in variable 'boc'")
        print("---------------------------------------")
        code.interact(local=locals())
    else:
        boc.populate()
        boc.plan()
        if args.dry_run:
            boc.report()
        else:
            boc.reap()
