"""Utilities for reading test data."""

from __future__ import annotations

from base64 import b64encode

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
from safir.testing.data import Data

__all__ = ["NubladoData"]


class NubladoData(Data):
    """Test data management wrapper class."""

    def read_nodes(self, path: str) -> list[V1Node]:
        """Read input node data.

        This only includes data used to select nodes and which images the node
        has cached, since this is the only thing the Nublado controller cares
        about.

        Parameters
        ----------
        path
            Path relative to :file:`tests/data`. A ``.json`` extension will be
            added automatically.

        Returns
        -------
        list of kubernetes_asyncio.client.V1Node
            Parsed contents of file.
        """
        nodes = []
        for name, data in self.read_json(path).items():
            images = [V1ContainerImage(**d) for d in data.get("images", [])]
            taints = [V1Taint(**t) for t in data.get("taints", [])]
            node = V1Node(
                metadata=V1ObjectMeta(name=name, labels=data.get("labels")),
                spec=V1NodeSpec(taints=taints),
                status=V1NodeStatus(images=images),
            )
            nodes.append(node)
        return nodes

    def read_secrets(self, path: str) -> list[V1Secret]:
        """Read Kubernetes secrets.

        These secrets should exist at the start of a test and contain secrets
        that may be read and merged to create the user lab secret.

        Parameters
        ----------
        path
            Path relative to :file:`tests/data`. A ``.json`` extension will be
            added automatically.

        Returns
        -------
        list of kubernetes_asyncio.client.V1Secret
            Corresponding Kubernetes ``Secret`` objects.
        """
        secrets = []
        for name, data in self.read_json(path).items():
            encoded = {
                k: b64encode(v.encode()).decode() for k, v in data.items()
            }
            secret = V1Secret(metadata=V1ObjectMeta(name=name), data=encoded)
            if ".dockerconfigjson" in data:
                secret.type = "kubernetes.io/dockerconfigjson"
            secrets.append(secret)
        return secrets

    def read_users(self, path: str) -> dict[str, GafaelfawrUserInfo]:
        """Read input Gafaelfawr user data.

        Parameters
        ----------
        path
            Path relative to :file:`tests/data`. A ``.json`` extension will be
            added automatically.

        Returns
        -------
        dict of GafaelfawrUserInfo
            Dictionary mapping usernames to `GafaelfawrUserInfo` objects.
        """
        data = self.read_json(path)
        return {
            t: GafaelfawrUserInfo.model_validate(u) for t, u in data.items()
        }
