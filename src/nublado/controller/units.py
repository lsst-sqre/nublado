"""Unit conversions for the Nublado controller."""

from __future__ import annotations

import re
from typing import Any

import bitmath

__all__ = ["bytes_to_si", "cpu_to_cores", "memory_to_bytes"]


def memory_to_bytes(memory: Any) -> int:
    """Convert a string representation of memory to a number of bytes.

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
    memory = str(memory)
    return int(bitmath.parse_string_unsafe(memory).bytes)


def bytes_to_si(val: int) -> str:
    """Convert a number of bytes into a human-readable SI string.

    This string shows units that could be used in a Kubernetes spec.

    Parameters
    ----------
    val
        An int quantity of bytes

    Returns
    -------
    str
        A human-readable quantity of bytes, like 3Gi
    """
    best_prefix = bitmath.Byte(val).best_prefix().format("{value:g}{unit}")
    return str(best_prefix).removesuffix("B")


def cpu_to_cores(cpu: Any) -> float:
    """Convert a Kubernetes CPU resource value to a float number of cores.

    https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/#meaning-of-cpu

    Parameters
    ----------
    cpu
        Kubernetes CPU resource value.

    Returns
    -------
    float
        Equivalent number of cores.

    Raises
    ------
    ValueError
        If the input string is not a valid Kubernetes CPU resource value.
    """
    cpu = str(cpu)
    msg = (
        "CPU must be specified as a whole number of milli-cores, like 500m, or"
        " a decimal number with no more than three places of precision, like"
        " 1.234"
    )
    # Specified in milli-cores, like 500m. No decimals allowed.
    pattern = r"^\d+m$"
    if re.match(pattern, cpu):
        millicpus = float(cpu[:-1])
        return millicpus / 1000

    # Specified in whole cores. More than three decimal places is not allowed.
    try:
        cores = float(cpu)
    except ValueError as exc:
        raise ValueError(msg) from exc

    if "." in cpu:
        _, part = cpu.split(".")
        if len(part) > 3:
            raise ValueError(msg)
    return cores
