"""Helpers for RSP startup logging; this is a stripped-down version of
what Safir does.
"""

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict

from ..constants import APP_NAME

__all__ = ["configure_logging"]


def configure_logging(*, debug: bool = False) -> None:
    """Stripped-down version of Safir's "configure_logging()"; we
    always add timestamps, and if we're not running with debugging,
    it's INFO-level JSON logs; if we are running with debugging,
    DEBUG-level text-format.

    Parameters
    ----------
    debug
        Enable debugging?  See above for effect.
    """
    log_level = "DEBUG" if debug else "INFO"
    stream_handler = logging.StreamHandler(stream=sys.stdout)
    stream_handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger(APP_NAME)
    logger.handlers = []
    logger.addHandler(stream_handler)
    logger.setLevel(log_level)
    processors: list[Any] = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
    ]
    processors.append(structlog.processors.TimeStamper(fmt="iso"))
    processors.extend(
        [
            structlog.processors.StackInfoRenderer(),
            structlog.processors.UnicodeDecoder(),
        ]
    )
    if debug:
        # Key-value formatted logging
        processors.append(structlog.stdlib.add_log_level)
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        # JSON-formatted logging
        processors.append(add_log_severity)
        processors.append(structlog.processors.format_exc_info)
        processors.append(structlog.processors.JSONRenderer())
    structlog.configure(
        processors=processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def add_log_severity(
    logger: logging.Logger, method_name: str, event_dict: EventDict
) -> EventDict:
    """Add the log level to the event dict as ``severity``.

    Intended for use as a structlog processor.

    This is the same as `structlog.stdlib.add_log_level` except that it
    uses the ``severity`` key rather than ``level`` for compatibility with
    Google Log Explorer and its automatic processing of structured logs.

    Parameters
    ----------
    logger
        The wrapped logger object.
    method_name
        The name of the wrapped method (``warning`` or ``error``, for
        example).
    event_dict
        Current context and current event. This parameter is also modified in
        place, matching the normal behavior of structlog processors.

    Returns
    -------
    ``structlog.types.EventDict``
        The modified ``structlog.types.EventDict`` with the added key.

    Notes
    -----
    This is stolen directly from Safir.
    """
    severity = structlog.stdlib.add_log_level(logger, method_name, {})["level"]
    event_dict["severity"] = severity
    return event_dict
