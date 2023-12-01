"""Construct Kubernetes objects used by the prepuller."""

from __future__ import annotations

import re

from kubernetes_asyncio.client import (
    V1Container,
    V1LocalObjectReference,
    V1ObjectMeta,
    V1Pod,
    V1PodSpec,
)

from ...models.domain.rspimage import RSPImage
from ...storage.metadata import MetadataStorage

__all__ = ["PrepullerBuilder"]


class PrepullerBuilder:
    """Construct Kubernetes objects used by the prepuller.

    Parameters
    ----------
    metadata_storage
        Storage layer for pod metadata about the lab controller itself.
    pull_secret
        Optional name of ``Secret`` object to use for pulling images.
    """

    def __init__(
        self, metadata_storage: MetadataStorage, pull_secret: str | None = None
    ) -> None:
        self._metadata = metadata_storage
        self._pull_secret = pull_secret

    def build_pod(self, image: RSPImage, node: str) -> V1Pod:
        """Construct the pod object for a prepuller pod.

        Parameters
        ----------
        image
            Image to prepull.
        node
            Node on which to prepull it.

        Returns
        -------
        kubernetes_asyncio.client.models.V1Pod
            Kubernetes ``Pod`` object to create.
        """
        pull_secrets = None
        if self._pull_secret:
            pull_secrets = [V1LocalObjectReference(name=self._pull_secret)]
        return V1Pod(
            metadata=V1ObjectMeta(
                name=self._build_pod_name(image, node),
                labels={"nublado.lsst.io/category": "prepuller"},
                owner_references=[self._metadata.owner_reference],
            ),
            spec=V1PodSpec(
                containers=[
                    V1Container(
                        name="prepull",
                        command=["/bin/true"],
                        image=image.reference_with_digest,
                        working_dir="/tmp",
                    )
                ],
                image_pull_secrets=pull_secrets,
                node_name=node,
                restart_policy="Never",
            ),
        )

    def _build_pod_name(self, image: RSPImage, node: str) -> str:
        """Create the pod name to use for prepulling an image.

        This embeds some information in the pod name that may be useful for
        debugging purposes.

        Parameters
        ----------
        image
            Image to prepull.
        node
            Node on which to prepull it.

        Returns
        -------
        str
            Pod name to use.
        """
        tag_part = image.tag.replace("_", "-")
        tag_part = re.sub(r"[^\w.-]", "", tag_part, flags=re.ASCII)
        name = f"prepull-{tag_part}-{node}"

        # Kubernetes object names may be at most 253 characters long.
        return name[:253]
