"""Constants for RSP startup."""

from pathlib import Path

__all__ = [
    "APP_NAME",
    "ETC_PATH",
    "MAX_NUMBER_OUTPUTS",
    "PREVIOUS_LOGGING_CHECKSUMS",
]

APP_NAME = "nublado"
"""Application name, used for logging."""

ETC_PATH = Path("/etc")
"""Configuration directory, usually /etc, but overrideable for tests."""

PREVIOUS_LOGGING_CHECKSUMS = [
    "2997fe99eb12846a1b724f0b82b9e5e6acbd1d4c29ceb9c9ae8f1ef5503892ec"
]
"""sha256 sums of previous iterations of ``20-logging.py``.

Used to determine whether upgrading the logging configuration is
needed, or whether the user has made local modifications that
therefore should not be touched.
"""

MAX_NUMBER_OUTPUTS = 10000
"""Maximum number of output lines to display in a Jupyter notebook cell.

Used to prevent OOM-killing if some cell generates a lot of output.
"""
