"""Reset the configuration and Docker client.  It is allowed and indeed
expected that you will call both of these with the same config path."""

from jupyterlabcontroller.dependencies.config import configuration_dependency
from jupyterlabcontroller.dependencies.docker import docker_client_dependency
from jupyterlabcontroller.models.v1.domain.config import Config
from jupyterlabcontroller.storage.docker import DockerClient


def config_config(config_path: str) -> Config:
    """Change the test application configuration.

    Parameters
    ----------
    config_path
      Path to a directory that contains a configuration file
      ``configuration.yaml``, which is the YAML that would usually be
      mounted into the container at ``/etc/nublado/config.yaml``.
    """
    configuration_dependency.set_configuration_path(
        f"{config_path}/config.yaml"
    )
    return configuration_dependency.config()


def docker_client(config_path: str) -> DockerClient:
    """Change the test application configuration.

    Parameters
    ----------
    config_path
      Path to a directory that contains a configuration file
      ``docker_config.json``, which would usually be found at
      ``/etc/secrets/.dockerconfigjson``.
    """
    docker_client_dependency.set_secrets_path(
        f"{config_path}/docker_config.json"
    )
    return docker_client_dependency.client()
