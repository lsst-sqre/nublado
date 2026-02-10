"""Launcher for JupyterLab, relying on Nublado init containers."""

import json
import os
import sys
from pathlib import Path
from typing import NoReturn

from ._constants import ARGS_PATH, ENV_PATH

__all__ = ["launch_lab"]


def launch_lab() -> NoReturn:
    """Start JupyterLab for Nublado.

    This entry point is installed into the Python virtualenv that includes
    JupyterLab. It is invoked by the entry point shell script configured in
    Nublado as a startup command for the main JupyterLab container, started
    after all the init containers have been run. It relies on files created in
    :file:`/etc/nublado/startup` by the Nublado init containers.

    It performs the following tasks:

    #. Merges the contents of :file:`/etc/nublado/startup/env.json` with the
       current environment (which is set by the Nublado controller based on
       its configuration and environment variables passed from JupyterHub).
    #. Reads the JupyterLab start command from
       :file:`/etc/nublado/startup/args.json`.
    #. Starts JupyterLab with those environment variables and command-line
       arguments.
    """
    try:
        with ENV_PATH.open("r") as fh:
            extra_env = json.load(fh)
        with ARGS_PATH.open("r") as fh:
            command = json.load(fh)
    except FileNotFoundError:
        # This fallback can be removed once all Nublado instances have been
        # updated to a version that always uses /etc/nublado/startup.
        with Path("/lab_startup/env.json").open("r") as fh:
            extra_env = json.load(fh)
        with Path("/lab_startup/args.json").open("r") as fh:
            command = json.load(fh)
    environ = os.environ.copy()
    environ.update(extra_env)
    sys.stdout.flush()
    sys.stderr.flush()
    os.execvpe(command[0], command, env=environ)
