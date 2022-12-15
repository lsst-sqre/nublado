"""Per-process prepuller state.  This is a singleton but instead of trying
to enforce that at the Python level it will live in the ProcessContext object
and thus will get initialized once per process.

This holds everything that we actually retrieve from Kubernetes or a Docker
repository.  The idea is that this state gets passed around the various
prepuller components; it is only refreshed by the background tasks.  The
rest of the components simply consult it and believe what it tells them,
and all of their operations are done in-memory.
"""

from typing import List

from ...constants import (
    EPOCH,
    PREPULLER_DOCKER_POLL_INTERVAL,
    PREPULLER_K8S_POLL_INTERVAL,
)
from ...models.domain.prepuller import Node, NodeTagImage, TagMap
from ...util import now, stale


class PrepullerState:
    def __init__(self) -> None:
        self._remote_images = TagMap()
        self._nodes: List[Node] = list()
        self._images: List[NodeTagImage] = list()
        self._last_docker_check = EPOCH
        self._last_k8s_check = EPOCH
        self._last_prepuller_run = EPOCH

    @property
    def needs_docker_refresh(self) -> bool:
        return stale(self._last_docker_check, PREPULLER_DOCKER_POLL_INTERVAL)

    @property
    def needs_k8s_refresh(self) -> bool:
        return stale(self._last_k8s_check, PREPULLER_K8S_POLL_INTERVAL)

    @property
    def needs_prepuller_refresh(self) -> bool:
        # Choose the smaller of the polling intervals
        interval = PREPULLER_K8S_POLL_INTERVAL
        if PREPULLER_DOCKER_POLL_INTERVAL < interval:
            interval = PREPULLER_DOCKER_POLL_INTERVAL
        return stale(self._last_prepuller_run, interval)

    def update_docker_check_time(self) -> None:
        self._last_docker_check = now()

    def update_k8s_check_time(self) -> None:
        self._last_k8s_check = now()

    def update_prepuller_run_time(self) -> None:
        self._last_prepuller_run = now()

    @property
    def remote_images(self) -> TagMap:
        return self._remote_images

    def set_remote_images(self, tag_map: TagMap) -> None:
        self._remote_images = tag_map

    @property
    def images(self) -> List[NodeTagImage]:
        return self._images

    def set_images(self, images: List[NodeTagImage]) -> None:
        self._images = images

    @property
    def nodes(self) -> List[Node]:
        return self._nodes

    def set_nodes(self, nodes: List[Node]) -> None:
        self._nodes = nodes
