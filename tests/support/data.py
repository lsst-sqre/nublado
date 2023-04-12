"""Utilities for reading test data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kubernetes_asyncio.client import (
    V1ContainerImage,
    V1Node,
    V1NodeStatus,
    V1ObjectMeta,
)

__all__ = [
    "read_input_data",
    "read_input_node_data",
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


def read_input_node_data(config: str, filename: str) -> list[V1Node]:
    """Read input node data as JSON and return it as a list of nodes.

    This only includes data about which images the node has cached, since this
    is the only thing the lab controller cares about.

    Parameters
    ----------
    config
        Configuration from which to read data (the name of one of the
        directories under ``tests/configs``).
    filename
        File to read and parse. Must be in JSON format.

    Returns
    -------
    list of kubernetes_asyncio.client.V1Node
        Parsed contents of file.
    """
    node_data = read_input_data(config, filename)
    nodes = []
    for name, data in node_data.items():
        node_images = [
            V1ContainerImage(names=d["names"], size_bytes=d["sizeBytes"])
            for d in data
        ]
        node = V1Node(
            metadata=V1ObjectMeta(name=name),
            status=V1NodeStatus(images=node_images),
        )
        nodes.append(node)
    return nodes


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
