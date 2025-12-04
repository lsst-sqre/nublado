"""Entry point for CST tutorial provisioner."""

import logging

from .provisioner import Provisioner

__all__ = ["main"]


def main() -> None:
    """Entry point for provisioner.

    Environment variables ``NUBLADO_HOME`` must be set.  This is
    Nublado-controller specific.

    The other three can come from the user environment or be defaulted.

    We never want to raise an exception from here: if the container fails,
    we still want to start the user lab, but the experience might be
    suboptimal.
    """
    logger = logging.getLogger("cst_tutorial_provisioner")
    logging.basicConfig()  # Not great but it'll do.
    try:
        provisioner = Provisioner.from_env()
        provisioner.go()
    except Exception:
        logger.exception("Provisioner failed")
