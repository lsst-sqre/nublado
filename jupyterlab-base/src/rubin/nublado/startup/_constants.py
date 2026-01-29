"""Constants for the JupyterLab startup code."""

from pathlib import Path

__all__ = [
    "ARGS_PATH",
    "ENV_PATH",
]

ARGS_PATH = Path("/etc/nublado/startup/args.json")
"""Path to JSON file containing a list of additional JupyterLab arguments."""

ENV_PATH = Path("/etc/nublado/startup/env.json")
"""Path to JSON file containing a dict of additional environment variables."""
