"""Construction of Kubernetes objects for user lab environments."""

from __future__ import annotations

from typing import Optional

from kubernetes_asyncio.client import (
    V1HostPathVolumeSource,
    V1NFSVolumeSource,
    V1Volume,
    V1VolumeMount,
)

from ..config import FileMode, LabConfig, LabVolume
from ..models.domain.lab import LabVolumeContainer

__all__ = ["LabBuilder"]


class LabBuilder:
    """Construct Kubernetes objects for user lab environments.

    Eventually, this class will be responsible for constructing all of the
    Kubernetes objects required for a lab environment. Currently, it contains
    the Kubernetes object construction code that is shared between
    `~jupyterlabcontroller.services.lab.LabManager` and
    `~jupyterlabcontroller.services.state.LabStateManager`, and also the
    Kubernetes volume construction code shared between the fileserver and
    the lab user object sets.

    Since it's not just the Lab anymore, it probably should have a more
    generic name like ObjectBuilder, but let's not worry about that until
    the non-fileserver work is merged.

    Parameters
    ----------
    config
        Lab configuration.
    """

    def __init__(self, config: LabConfig) -> None:
        self._config = config

    def build_internal_url(self, username: str, env: dict[str, str]) -> str:
        """Determine the URL of a newly-spawned lab.

        The hostname and port are fixed to match the Kubernetes ``Service`` we
        create, but the local part is normally determined by an environment
        variable passed from JupyterHub.

        Parameters
        ----------
        username
            Username of lab user.
        env
            Environment variables from JupyterHub.

        Returns
        -------
        str
            URL of the newly-spawned lab.
        """
        namespace = self.namespace_for_user(username)
        path = env["JUPYTERHUB_SERVICE_PREFIX"]
        return f"http://lab.{namespace}:8888" + path

    def recreate_env(self, env: dict[str, str]) -> dict[str, str]:
        """Recreate the JupyterHub-provided environment.

        When reconciling state from Kubernetes, we need to recover the content
        of the environment sent from JupyterHub from the ``ConfigMap`` in the
        user's lab environment. We can't recover the exact original
        environment, but we can recreate an equivalent one by filtering out
        the environment variables that would be set directly by the lab
        controller.

        Parameters
        ----------
        env
            Environment recovered from a ``ConfigMap``.

        Returns
        -------
        dict of str to str
            Equivalent environment sent by JupyterHub.

        Notes
        -----
        The list of environment variables that are always added internally by
        the lab controller must be kept in sync with the code that creates the
        config map.
        """
        unwanted = set(
            (
                "CPU_GUARANTEE",
                "CPU_LIMIT",
                "DEBUG",
                "EXTERNAL_INSTANCE_URL",
                "IMAGE_DESCRIPTION",
                "IMAGE_DIGEST",
                "JUPYTER_IMAGE",
                "JUPYTER_IMAGE_SPEC",
                "MEM_GUARANTEE",
                "MEM_LIMIT",
                "RESET_USER_ENV",
                *list(self._config.env.keys()),
            )
        )
        return {k: v for k, v in env.items() if k not in unwanted}

    def namespace_for_user(self, username: str) -> str:
        """Construct the namespace name for a user's lab environment.

        Parameters
        ----------
        username
            Username of lab user.

        Returns
        -------
        str
            Name of their namespace.
        """
        return f"{self._config.namespace_prefix}-{username}"

    def build_lab_config_volumes(
        self, prefix: str = "", config: Optional[list[LabVolume]] = None
    ) -> list[LabVolumeContainer]:
        """Construct LabVolumeContainers for a specified list of LabVolumes

        Parameters
        ----------
        prefix
            Path to prepend to Lab volumes (defaults to the empty string)
        config
            List of LabVolumes.  Optional, defaults to what's specified in
            the Lab configuration

        Returns
        -------
        list[LabVolumeContainer]
            LabVolumeContainers for attaching to a Pod
        """
        # We provide prefix for the use of the fileserver: because a WebDAV
        # client must have a single endpoint, we aggregate the volume mounts
        # in the fileserver pod under a single prefix, and export that prefix
        # as the WebDAV endpoint.  There's no such requirement in Lab pods,
        # which are going to mount filesystems all over the place.
        #
        # We allow specification of the config so we can build initContainers,
        # which might only have a subset of the Lab volumes
        #
        # The default is to use the Lab volumes from the configuration
        if config is None:
            input_volumes = self._config.volumes
        else:
            input_volumes = config
        vols = []
        for storage in input_volumes:
            ro = False
            if storage.mode == FileMode.RO:
                ro = True
            vname = storage.container_path.replace("/", "_")[1:]
            if not storage.server:
                vol = V1Volume(
                    host_path=V1HostPathVolumeSource(path=storage.server_path),
                    name=vname,
                )
            else:
                vol = V1Volume(
                    nfs=V1NFSVolumeSource(
                        path=storage.server_path,
                        read_only=ro,
                        server=storage.server,
                    ),
                    name=vname,
                )
            vm = V1VolumeMount(
                mount_path=prefix + storage.container_path,
                read_only=ro,
                name=vname,
            )
            vols.append(LabVolumeContainer(volume=vol, volume_mount=vm))
        return vols
