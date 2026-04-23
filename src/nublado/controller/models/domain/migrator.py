"""Models for the migrator pod state."""

from .fsadmin import FSAdminObjects

__all__ = ["MigratorObjects", "build_migrator_pod_name"]


def build_migrator_pod_name(old_user: str, new_user: str) -> str:
    """Build pod name for a migrator pod.

    Parameters
    ----------
    old_user
        Username for source user to copy from.
    new_user
        Username for target user to copy to.

    Returns
    -------
    str
        Name of migrator pod.
    """
    return f"migrator-{old_user}-to-{new_user}"


class MigratorObjects(FSAdminObjects):
    """All of the Kubernetes objects making up a migrator."""
