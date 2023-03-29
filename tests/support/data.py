"""Utilities for reading test data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = [
    "read_input_data",
    "read_output_data",
]


def read_input_data(config: str, filename: str) -> Any:
    """Read input data as JSON and return its decoded form.

    Parameters
    ----------
    config
        Configuration from which to read data (the name of one of the
        directories under ``tests/configs``).
    filename
        File to read and parse. Must be in JSON format.

    Returns
    -------
    typing.Any
        Parsed contents of file.
    """
    base_path = Path(__file__).parent.parent / "configs" / config
    with (base_path / "input" / filename).open("r") as f:
        return json.load(f)


def read_output_data(config: str, filename: str) -> Any:
    """Read output data as JSON and return its decoded form.

    Parameters
    ----------
    config
        Configuration from which to read data (the name of one of the
        directories under ``tests/configs``).
    filename
        File to read and parse. Must be in JSON format.

    Returns
    -------
    typing.Any
        Parsed contents of file.
    """
    base_path = Path(__file__).parent.parent / "configs" / config
    with (base_path / "output" / filename).open("r") as f:
        return json.load(f)
