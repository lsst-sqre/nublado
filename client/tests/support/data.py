"""Utilities for reading test data."""

from __future__ import annotations

from pathlib import Path

__all__ = ["read_test_data"]


def read_test_data(filename: str) -> str:
    """Read an input data file and return its contents.

    Parameters
    ----------
    config
        Configuration from which to read data (the name of one of the
        directories under :file:`tests/data`).
    filename
        File to read.

    Returns
    -------
    str
        Contents of the file.
    """
    return (Path(__file__).parent.parent / "data" / filename).read_text()
