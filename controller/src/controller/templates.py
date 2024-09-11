"""Template management.

Provides a shared Jinja template environment used whenever the Nublado
controller generates responses based on templates.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi.templating import Jinja2Templates
from jinja2 import Environment, PackageLoader

__all__ = ["templates"]

templates = Jinja2Templates(
    env=Environment(
        loader=PackageLoader("controller", package_path="templates"),
        autoescape=True,
    ),
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
        Human-readable equivalent. Daylight saving time transitions are not
        taken into account.
    """
    seconds = int(delta.total_seconds())
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    string = ""
    if days:
        string = f"{days} " + ("day" if days == 1 else "days")
    if hours:
        if string:
            string += " "
        string += f"{hours} " + ("hour" if hours == 1 else "hours")
    if minutes:
        if string:
            string += " "
        string += f"{minutes} " + ("minute" if minutes == 1 else "minutes")
    if seconds:
        if string:
            string += " "
        string += f"{seconds} " + ("second" if seconds == 1 else "seconds")
    return string


templates.env.filters["format_timedelta"] = _format_timedelta
