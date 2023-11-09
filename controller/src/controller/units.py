"""Unit conversions for the Nublado controller."""

from __future__ import annotations

import bitmath

__all__ = ["memory_to_bytes"]


def memory_to_bytes(memory: str) -> int:
    """Convert a string representatio of memory to a number of bytes.

    Parameters
    ----------
    memory
        Amount of memory as a string.

    Returns
    -------
    int
        Equivalent number of bytes.

    Raises
    ------
    ValueError
        Raised if the input string is not a valid byte specification.
    """
    return int(bitmath.parse_string_unsafe(memory).bytes)
