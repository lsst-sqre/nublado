"""Collection of types of container registries we might encounter."""

from enum import Enum


class RegistryCategory(Enum):
    """Each registry category has its own way of deleting objects, and some
    have more efficient ways to list objects than the Docker Repository API.
    """

    DOCKERHUB = "hub.docker.com"
    GHCR = "ghcr.io"
    GAR = "pkg.dev"
    NEXUS = "<generic Nexus>"
    DOCKER = "<generic Docker>"
