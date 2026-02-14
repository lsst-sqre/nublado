"""Utilities for reading test data."""

from __future__ import annotations

from base64 import b64encode
from collections.abc import Iterable

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
from safir.testing.kubernetes import strip_none

from nublado.controller.models.domain.kubernetes import KubernetesModel

__all__ = ["NubladoData"]


class NubladoData(Data):
    """Test data management wrapper class."""

    def assert_kubernetes_matches(
        self,
        objects_raw: Iterable[dict | KubernetesModel],
        path: str,
    ) -> None:
        """Serialize a list of Kubernetes objects and compare them.

        We often want to compare the contents of the mock Kubernetes with an
        expected set of objects. This method serializes the Kubernetes
        objects, strips data that changes always changes in every run, and
        compares to stored data in JSON format.

        Parameters
        ----------
        objects
            List of objects to serialize, which may include custom objects
            that are represented by raw dicts.
        path
            Path relative to :file:`tests/data`. A ``.json`` extension will be
            added automatically.
        """
        objects = []
        for obj in objects_raw:
            if isinstance(obj, dict):
                serialized = obj
            else:
                serialized = obj.to_dict(serialize=True)

            # These attributes intentionally may change on every test run and
            # thus should not be compared. Change them to None so that they'll
            # be stripped by strip_none.
            serialized["metadata"]["resourceVersion"] = None
            if "status" in serialized and serialized["status"] is not None:
                serialized["status"]["startTime"] = None

            objects.append(strip_none(serialized))

        # Delegate the actual comparison to the standard JSON matcher.
        self.assert_json_matches(objects, path)

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
