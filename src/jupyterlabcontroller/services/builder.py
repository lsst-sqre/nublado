"""Construction of Kubernetes objects for user lab environments."""

from __future__ import annotations

from ..config import LabConfig

__all__ = ["LabBuilder"]


class LabBuilder:
    """Construct Kubernetes objects for user lab environments.

    Eventually, this class will be responsible for constructing all of the
    Kubernetes objects required for a lab environment. Currently, it contains
    only the Kubernetes object construction code that is shared between
    `~jupyterlabcontroller.services.lab.LabManager` and
    `~jupyterlabcontroller.services.state.LabStateManager`.

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
