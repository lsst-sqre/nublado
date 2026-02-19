"""Storage layer for pod metadata."""

from functools import cached_property
from pathlib import Path

from kubernetes_asyncio.client import V1OwnerReference

__all__ = ["MetadataStorage"]


class MetadataStorage:
    """Storage layer for pod metadata for the running pod.

    Some attributes of the Kubernetes objects created by the lab controller
    depend on metadata about where the lab controller is running. This storage
    layer retrieves that information via the Kubernetes `downward API`_.

    Parameters
    ----------
    metadata_path
        Path at which the downward API data is mounted.
    """

    def __init__(self, metadata_path: Path) -> None:
        self._path = metadata_path

    @cached_property
    def namespace(self) -> str:
        """The namespace in which the lab controller is running.

        Some resources, such as prepuller pods, are spawned in the same
        namespace as the lab controller.
        """
        return (self._path / "namespace").read_text().strip()

    @cached_property
    def owner_reference(self) -> V1OwnerReference:
        """An owner reference pointing to the lab controller.

        We want some objects, such as prepuller pods, to show as owned by the
        lab controller. This enables clearer display in services such as Argo
        CD and also hopefully tells Kubernetes to delete the pods when the lab
        controller is deleted, avoiding later conflicts.
        """
        name_path = self._path / "name"
        uid_path = self._path / "uid"
        return V1OwnerReference(
            api_version="v1",
            kind="Pod",
            name=name_path.read_text().strip(),
            uid=uid_path.read_text().strip(),
            block_owner_deletion=True,
        )
