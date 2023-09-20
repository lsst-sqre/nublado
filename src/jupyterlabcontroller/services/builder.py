"""Construction of Kubernetes objects for user lab environments."""

from __future__ import annotations

import re

from kubernetes_asyncio.client import (
    V1Container,
    V1HostPathVolumeSource,
    V1LocalObjectReference,
    V1NFSVolumeSource,
    V1ObjectMeta,
    V1PersistentVolumeClaimVolumeSource,
    V1Pod,
    V1PodSpec,
    V1Volume,
    V1VolumeMount,
)

from ..config import (
    FileMode,
    HostPathVolumeSource,
    LabConfig,
    LabVolume,
    NFSVolumeSource,
    PVCVolumeSource,
)
from ..models.domain.lab import LabVolumeContainer
from ..models.domain.rspimage import RSPImage
from ..storage.metadata import MetadataStorage

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
        dict of str
            Equivalent environment sent by JupyterHub.

        Notes
        -----
        The list of environment variables that are always added internally by
        the lab controller must be kept in sync with the code that creates the
        config map.
        """
        unwanted = {
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
        }
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
        self, username: str, config: list[LabVolume], prefix: str = ""
    ) -> list[LabVolumeContainer]:
        #
        # Step one: disks specified in config, whether for the lab itself
        # or one of its init containers.
        #
        vols = []
        pvc = 1
        for storage in config:
            ro = storage.mode == FileMode.RO
            vname = storage.container_path.replace("/", "-")[1:].lower()
            match storage.source:
                case HostPathVolumeSource() as source:
                    vol = V1Volume(
                        host_path=V1HostPathVolumeSource(path=source.path),
                        name=vname,
                    )
                case NFSVolumeSource() as source:
                    vol = V1Volume(
                        nfs=V1NFSVolumeSource(
                            path=source.server_path,
                            read_only=ro,
                            server=source.server,
                        ),
                        name=vname,
                    )
                case PVCVolumeSource():
                    pvc_name = f"{username}-nb-pvc-{pvc}"
                    pvc += 1
                    claim = V1PersistentVolumeClaimVolumeSource(
                        claim_name=pvc_name,
                        read_only=ro,
                    )
                    vol = V1Volume(persistent_volume_claim=claim, name=vname)
            vm = V1VolumeMount(
                mount_path=prefix + storage.container_path,
                sub_path=storage.sub_path,
                read_only=ro,
                name=vname,
            )
            vols.append(LabVolumeContainer(volume=vol, volume_mount=vm))
        return vols


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
        kubernetes_asyncio.client.V1Pod
            Kubernetes ``Pod`` object to create.
        """
        pull_secrets = []
        if self._pull_secret:
            pull_secrets.append(V1LocalObjectReference(name=self._pull_secret))
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
                        command=["/bin/sleep", "5"],
                        image=image.reference_with_digest,
                        working_dir="/tmp",
                    )
                ],
                image_pull_secrets=pull_secrets if pull_secrets else None,
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
