"""Test unit conversions."""

import pytest

from nublado.controller.units import bytes_to_si, cpu_to_cores, memory_to_bytes


def test_memory_to_bytes() -> None:
    assert memory_to_bytes(123456789) == 123456789
    assert memory_to_bytes("123456789") == 123456789
    assert memory_to_bytes("12K") == 12 * 1000
    assert memory_to_bytes("12Ki") == 12 * 1024
    assert memory_to_bytes("12M") == 12 * 1000 * 1000
    assert memory_to_bytes("12Mi") == 12 * 1024 * 1024
    assert memory_to_bytes("12MiB") == 12 * 1024 * 1024
    assert memory_to_bytes("1Gi") == 1024 * 1024 * 1024

    with pytest.raises(ValueError, match="not a valid"):
        assert memory_to_bytes("nope")


def test_bytes_to_human() -> None:
    assert bytes_to_si(123456789) == "117.738Mi"
    assert bytes_to_si(12 * 1024) == "12Ki"
    assert bytes_to_si(12 * 1024 * 1024) == "12Mi"
    assert bytes_to_si(1024 * 1024 * 1024) == "1Gi"


def test_cpu_to_cores() -> None:
    assert cpu_to_cores(1) == 1.0
    assert cpu_to_cores(1.234) == 1.234
    assert cpu_to_cores("1") == 1.0
    assert cpu_to_cores("1.234") == 1.234
    assert cpu_to_cores("450m") == 0.45
    assert cpu_to_cores("1450m") == 1.45

    with pytest.raises(ValueError, match="CPU must be specified"):
        cpu_to_cores(1.2345)

    with pytest.raises(ValueError, match="CPU must be specified"):
        cpu_to_cores("1.2m")

    with pytest.raises(ValueError, match="CPU must be specified"):
        cpu_to_cores("nope")
