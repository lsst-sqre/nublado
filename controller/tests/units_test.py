"""Test unit conversions."""

from __future__ import annotations

from controller.units import memory_to_bytes


def test_memory_to_bytes() -> None:
    assert memory_to_bytes("123456789") == 123456789
    assert memory_to_bytes("12K") == 12 * 1000
    assert memory_to_bytes("12Ki") == 12 * 1024
    assert memory_to_bytes("12M") == 12 * 1000 * 1000
    assert memory_to_bytes("12Mi") == 12 * 1024 * 1024
    assert memory_to_bytes("12MiB") == 12 * 1024 * 1024
    assert memory_to_bytes("1Gi") == 1024 * 1024 * 1024
