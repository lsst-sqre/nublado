"""Template management.

Provides a shared Jinja template environment used whenever the Nublado
controller generates responses based on templates.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi.templating import Jinja2Templates
from jinja2 import PackageLoader

__all__ = ["templates"]

# Starlette requires a directory argument, but since we override the loader so
# that the templates are retrieved from the Python package, it's unused.
templates = Jinja2Templates(
    loader=PackageLoader("controller", package_path="templates"),
    directory="templates",
)
"""The template manager."""


def _format_timedelta(delta: timedelta) -> str:
    """Format a `~datetime.timedelta` as a human-readable string.

    Parameters
    ----------
    delta
        Duration to format.

    Returns
    -------
    str
        Human-readable equivalent using ``d`` for days, ``h`` for hours, ``m``
        for minutes, and ``s`` for seconds. Daylight saving time transitions
        are not taken into account.
    """
    seconds = int(delta.total_seconds())
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    string = ""
    if days:
        string = f"{days}d"
    if hours:
        string += f"{hours}h"
    if minutes:
        string += f"{minutes}m"
    if seconds:
        string += f"{seconds}s"
    return string


templates.env.filters["format_timedelta"] = _format_timedelta
