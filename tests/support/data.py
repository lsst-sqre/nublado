"""Utilities for reading test data."""

from __future__ import annotations

import json
import os
from base64 import b64encode
from pathlib import Path
from typing import Any

from kubernetes_asyncio.client import (
    V1ContainerImage,
    V1Node,
    V1NodeSpec,
    V1NodeStatus,
    V1ObjectMeta,
    V1Secret,
    V1Taint,
)
from rubin.gafaelfawr import GafaelfawrUserInfo

from nublado.controller.models.v1.lab import LabSpecification

__all__ = [
    "read_input_data",
    "read_input_json",
    "read_input_lab_specification_json",
    "read_input_node_json",
    "read_input_secrets_json",
    "read_input_users_json",
    "read_output_data",
    "read_output_json",
    "write_output_json",
]


def assert_json_output_matches(seen: Any, config: str, filename: str) -> None:
    """Read expected output and assert the seen output matches.

    If the environment variable ``OVERWRITE_OUTPUT`` is set to a true value,
    the file holding the expected output will instead be replaced with a
    formatted version of the seen output, allowing easy update of complex test
    data.

    Parameters
    ----------
    seen
        Output seen in the test.
    config
        Configuration from which to read data (the name of one of the
        directories under :file:`tests/data`).
    filename
        File to read.
    """
    if os.getenv("OVERWRITE_OUTPUT"):
        write_output_json(config, filename, seen)
    else:
        assert seen == read_output_json(config, filename)


def read_input_data(config: str, filename: str) -> str:
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
    base_path = Path(__file__).parent.parent / "data" / "controller" / config
    return (base_path / "input" / filename).read_text()


def read_input_json(config: str, filename: str) -> Any:
    """Read input data as JSON and return its decoded form.

    Parameters
    ----------
    config
        Configuration from which to read data (the name of one of the
        directories under :file:`tests/data`). Omit the ``.json`` extension.
    filename
        File to read and parse. Must be in JSON format.

    Returns
    -------
    typing.Any
        Parsed contents of file.
    """
    base_path = Path(__file__).parent.parent / "data" / "controller" / config
    with (base_path / "input" / (filename + ".json")).open("r") as f:
        return json.load(f)


def read_input_lab_specification_json(
    config: str, filename: str
) -> LabSpecification:
    """Read lab creation input data in JSON.

    Parameters
    ----------
    config
        Configuration from which to read data (the name of one of the
        directories under :file:`tests/data`). Omit the ``.json`` extension.
    filename
        File to read and parse. Must be in JSON format.

    Returns
    -------
    LabSpecification
        Corresponding lab specification information, suitable for passing to
        the API to create a lab.
    """
    return LabSpecification.model_validate(read_input_json(config, filename))


def read_input_node_json(config: str, filename: str) -> list[V1Node]:
    """Read input node data as JSON and return it as a list of nodes.

    This only includes data used to select nodes and which images the node has
    cached, since this is the only thing the Nublado controller cares about.

    Parameters
    ----------
    config
        Configuration from which to read data (the name of one of the
        directories under :file:`tests/data`). Omit the ``.json`` extension.
    filename
        File to read and parse. Must be in JSON format.

    Returns
    -------
    list of kubernetes_asyncio.client.V1Node
        Parsed contents of file.
    """
    nodes = []
    for name, data in read_input_json(config, filename).items():
        node_images = [
            V1ContainerImage(names=d["names"], size_bytes=d["sizeBytes"])
            for d in data.get("images", [])
        ]
        taints = [V1Taint(**t) for t in data.get("taints", [])]
        node = V1Node(
            metadata=V1ObjectMeta(name=name, labels=data.get("labels")),
            spec=V1NodeSpec(taints=taints),
            status=V1NodeStatus(images=node_images),
        )
        nodes.append(node)
    return nodes


def read_input_secrets_json(config: str, filename: str) -> list[V1Secret]:
    """Read Kubernetes secrets.

    These secrets should exist at the start of a test and contain secrets that
    may be read and merged to create the user lab secret.

    Parameters
    ----------
    config
        Configuration from which to read data (the name of one of the
        directories under :file:`tests/data`). Omit the ``.json`` extension.
    filename
        File to read and parse. Must be in JSON format.

    Returns
    -------
    list of kubernetes_asyncio.client.V1Secret
        Corresponding Kubernetes ``Secret`` objects.
    """
    secrets = []
    for name, data in read_input_json(config, filename).items():
        encoded = {k: b64encode(v.encode()).decode() for k, v in data.items()}
        secret = V1Secret(metadata=V1ObjectMeta(name=name), data=encoded)
        if ".dockerconfigjson" in data:
            secret.type = "kubernetes.io/dockerconfigjson"
        secrets.append(secret)
    return secrets


def read_input_users_json(
    config: str, filename: str
) -> dict[str, GafaelfawrUserInfo]:
    """Read input Gafaelfawr user data.

    Parameters
    ----------
    config
        Configuration from which to read data (the name of one of the
        directories under :file:`tests/data`). Omit the ``.json`` extension.
    filename
        File to read and parse. Must be in JSON format.

    Returns
    -------
    dict of GafaelfawrUserInfo
        Dictionary mapping usernames to `GafaelfawrUserInfo` objects.
    """
    data = read_input_json(config, filename)
    return {t: GafaelfawrUserInfo.model_validate(u) for t, u in data.items()}


def read_output_data(config: str, filename: str) -> str:
    """Read an output data file and return its contents.

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
    base_path = Path(__file__).parent.parent / "data" / "controller" / config
    return (base_path / "output" / filename).read_text()


def read_output_json(config: str, filename: str) -> Any:
    """Read output data as JSON and return its decoded form.

    Parameters
    ----------
    config
        Configuration from which to read data (the name of one of the
        directories under :file:`tests/data`). Omit the ``.json`` extension.
    filename
        File to read and parse. Must be in JSON format.

    Returns
    -------
    typing.Any
        Parsed contents of file.
    """
    base_path = Path(__file__).parent.parent / "data" / "controller" / config
    with (base_path / "output" / (filename + ".json")).open("r") as f:
        return json.load(f)


def write_output_json(config: str, filename: str, data: Any) -> None:
    """Store output data as JSON.

    This function is not called directly by the test suite. It is provided as
    a convenience to write the existing output as test data so that a human
    can review it without having to write it manually.

    Parameters
    ----------
    config
        Configuration to which to write data (the name of one of the
        directories under :file:`tests/data`). Omit the ``.json`` extension.
    filename
        File to write.
    data
        Data to write.
    """
    base_path = Path(__file__).parent.parent / "data" / "controller" / config
    with (base_path / "output" / (filename + ".json")).open("w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
