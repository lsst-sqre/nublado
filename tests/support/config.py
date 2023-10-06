"""Build test configurations for the Nublado lab controller."""

from __future__ import annotations

from pathlib import Path

from kubernetes_asyncio.client import V1Namespace, V1ObjectMeta
from safir.testing.kubernetes import MockKubernetesApi

from jupyterlabcontroller.config import Config
from jupyterlabcontroller.dependencies.config import configuration_dependency
from jupyterlabcontroller.dependencies.context import context_dependency

__all__ = ["configure"]


async def configure(
    directory: str, mock_kubernetes: MockKubernetesApi | None = None
) -> Config:
    """Configure or reconfigure with a test configuration.

    If the global process context was already initialized, stop the background
    processes and restart them with the new configuration.

    Parameters
    ----------
    directory
        Configuration directory to use.
    mock_kubernetes
        Mock Kubernetes, required to create the namespace for fileservers if
        fileservers are enabled in the configuration.

    Returns
    -------
    Config
        New configuration.
    """
    config_path = Path(__file__).parent.parent / "data" / directory / "input"
    base_path = Path(__file__).parent.parent / "data" / "base" / "input"
    configuration_dependency.set_path(config_path / "config.yaml")
    config = configuration_dependency.config

    # Adjust the configuration to point to external objects if they're present
    # in the configuration directory.
    if (config_path / "docker-creds.json").exists():
        config.docker_secrets_path = config_path / "docker-creds.json"
    else:
        config.docker_secrets_path = base_path / "docker-creds.json"
    if (config_path / "metadata").exists():
        config.metadata_path = config_path / "metadata"
    else:
        config.metadata_path = base_path / "metadata"

    # If the new configuration enables fileservers, create the namespace for
    # the fileserver pods. Existence of the fileserver namespace is checked
    # when the background jobs start up, so this has to be done before
    # restarting the background jobs. This is quite annoying since it means we
    # need access to the mock Kubernetes layer, which complicates the API, but
    # there doesn't seem to be a way around it.
    if config.fileserver.enabled:
        assert mock_kubernetes, "Fileservers enabled, need mock_kubernetes"
        namespace = config.fileserver.namespace
        obj = V1Namespace(metadata=V1ObjectMeta(name=namespace))
        await mock_kubernetes.create_namespace(obj)

    # If the process context was initialized, meaning that we already have
    # running background jobs with the old configuration, stop and restart
    # them with the new configuration.
    if context_dependency.is_initialized:
        await context_dependency.aclose()
        await context_dependency.initialize(config)

    # Return the new configuration.
    return configuration_dependency.config
