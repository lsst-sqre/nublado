"""Entry point for inithome command."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from .provisioner import Provisioner

__all__ = ["main"]


def main() -> None:
    """Entry point for provisioner.

    Environment variables ``NUBLADO_HOME``, ``NUBLADO_UID``, and
    ``NUBLADO_GID`` must be set.
    """
    uid = int(os.environ["NUBLADO_UID"])
    gid = int(os.environ["NUBLADO_GID"])
    home = Path(os.environ["NUBLADO_HOME"])
    provisioner = Provisioner(home, uid, gid)
    asyncio.run(provisioner.provision())
