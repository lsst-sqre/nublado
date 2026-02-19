"""Models for mounted volumes."""

from dataclasses import dataclass

from kubernetes_asyncio.client import V1Volume, V1VolumeMount

__all__ = ["MountedVolume"]


@dataclass
class MountedVolume:
    """Represents a volume along with its corresponding mount.

    It's often more convenient to construct its volume (which is defined at
    the pod level) and its mount point (defined at the container level)
    together and only separate them when constructing Kubernetes objects.
    """

    volume: V1Volume
    """Kubernetes volume definition."""

    volume_mount: V1VolumeMount
    """Mount definiton for that volume within a container."""
