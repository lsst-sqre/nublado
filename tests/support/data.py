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


def write_output_data(config: str, filename: str, data: Any) -> None:
    """Store output data as JSON.

    This function is not called directly by the test suite. It is provided as
    a convenience to write the existing output as test data so that a human
    can review it without having to write it manually.

    Parameters
    ----------
    config
        Configuration to which to write data (the name of one of the
        directories under ``tests/configs``).
    filename
        File to write.
    data
        Data to write.
    """
    base_path = Path(__file__).parent.parent / "configs" / config
    with (base_path / "output" / filename).open("w") as f:
        json.dump(data, f, indent=2)
