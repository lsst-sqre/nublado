import os

from ...config import ContainerImage
from ...models.domain.kubernetes import PullPolicy


def _introspect_container() -> ContainerImage:
    """Determine the registry/repository/tag of the running container.
    This comes from the Phalanx deployment chart.
    It would be nice if the DownwardAPI gave us this, but it does not.
    """
    repository = os.getenv(
        "NUBLADO_CONTROLLER_REPOSITORY", "ghcr.io/lsst-sqre/nublado"
    )
    # We're guessing that version 11 will be the first place this shows up.
    tag = os.getenv("NUBLADO_CONTROLLER_TAG", "11.0.0")
    pull_policy_str = os.getenv(
        "NUBLADO_CONTROLLER_PULL_POLICY", "IfNotPresent"
    )
    if pull_policy_str.lower() == "always":
        pull_policy = PullPolicy.ALWAYS
    elif pull_policy_str.lower() == "never":
        pull_policy = PullPolicy.NEVER
    else:
        pull_policy = PullPolicy.IF_NOT_PRESENT

    return ContainerImage(
        repository=repository, pull_policy=pull_policy, tag=tag
    )
