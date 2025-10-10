"""The Nublado file purger service."""

from importlib.metadata import PackageNotFoundError, version

from .purger import Purger

__all__ = ["Purger", "__version__"]


__version__: str
"""The application version string (PEP 440 / SemVer compatible)."""

try:
    __version__ = version(__name__)
except PackageNotFoundError:
    # package is not installed
    __version__ = "0.0.0"
