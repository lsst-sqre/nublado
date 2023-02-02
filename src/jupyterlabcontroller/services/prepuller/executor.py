"""The Executor, like State, should be a process singleton.  Its job is to
orchestrate the things the prepuller needs to do that actually call external
services (either Kubernetes or Docker).
"""

import asyncio
from typing import Optional, Set

from aiojobs import Scheduler
from structlog.stdlib import BoundLogger

from ...constants import PREPULLER_INTERNAL_POLL_PERIOD, PREPULLER_PULL_TIMEOUT
from ...models.v1.prepuller_config import PrepullerConfiguration
from ...storage.docker import DockerStorageClient
from ...storage.k8s import K8sStorageClient
from ...util import image_to_podname
from .arbitrator import PrepullerArbitrator
from .docker import PrepullerDockerClient
from .k8s import PrepullerK8sClient
from .state import PrepullerState
from .tag import PrepullerTagClient

internal_poll_interval = 1.0


class PrepullerExecutor:
    def __init__(
        self,
        state: PrepullerState,
        k8s_client: K8sStorageClient,
        docker_client: DockerStorageClient,
        arbitrator: PrepullerArbitrator,
        logger: BoundLogger,
        config: PrepullerConfiguration,
        namespace: str,
    ) -> None:
        self.state = state
        self.tag_client = PrepullerTagClient(
            state=state, logger=logger, config=config
        )
        self.k8s_client = PrepullerK8sClient(
            state=self.state,
            k8s_client=k8s_client,
            logger=logger,
            tag_client=self.tag_client,
            config=config,
            namespace=namespace,
        )
        self.docker_client = PrepullerDockerClient(
            state=self.state, docker_client=docker_client, namespace=namespace
        )
        self.logger = logger
        self.namespace = namespace
        self.arbitrator = arbitrator
        self._docker_scheduler = Scheduler()
        self._k8s_scheduler = Scheduler()
        self._master_prepull_scheduler = Scheduler()
        self._prepull_scheduler: Optional[Scheduler] = None
        self._stopping = False
        self._running = False
        self._prepull_tasks: Set[asyncio.Task] = set()

    async def start(self) -> None:
        if self._stopping:
            self.logger.error(
                "Cannot start prepuller background tasks "
                "while they are stopping."
            )
            return
        if self._running:
            self.logger.info("Prepuller background tasks are already running.")
            return
        self.logger.info("Starting prepuller background tasks")
        await self._docker_scheduler.spawn(self._docker_refresh())
        # We want the remote list to populate before we look at what we
        # have locally.
        await self._wait_for_remote_images_to_populate()
        await self._k8s_scheduler.spawn(self._k8s_refresh())
        await self._master_prepull_scheduler.spawn(
            self._prepuller_scheduler_start()
        )
        self._running = True

    async def stop(self) -> None:
        self.logger.info("Stopping prepuller background tasks")
        self.stopping = True
        if not self._running:
            self.logger.info(
                "Prepuller background tasks were already stopped."
            )
        await self._docker_scheduler.close()
        await self._k8s_scheduler.close()
        if self._prepull_scheduler is not None:
            await self._wait_for_prepuller_close()
        await self._master_prepull_scheduler.close()
        self._stopping = False
        self._running = False

    async def _wait_for_remote_images_to_populate(self) -> None:
        """This is a minor optimization.  Basically, if we do not wait for
        the remote images to update, we won't have nice display name
        resolution for alias tags (such as "Recommended") until the first run
        of the local image scan *after* the remote scan has completed.

        If this method fails, the attempted image renaming will cause an
        error in the log and potential difficulty debugging what container
        a user is actually running, but doesn't break anything major.

        45 seconds is arbitrary.
        """
        increment = PREPULLER_INTERNAL_POLL_PERIOD
        total_wait = 0.0
        max_wait = 45.0
        while not self.state.remote_images.by_digest:
            await asyncio.sleep(increment)
            total_wait += increment
            increment *= 1.5
            self.logger.info(
                f"Waited for remote images for {total_wait}s so far"
            )
            if total_wait > max_wait:
                self.logger.error("Ceasing to wait for remote images.")
                return

    async def _prepuller_scheduler_start(self) -> None:
        # Poll until we see that we have data in our local and remote state
        # caches, then kick off a prepuller.  If something is wrong with
        # either K8s or the Docker repo, we will not start a prepuller until
        # they have successfully updated the images
        while not self._stopping:
            while (
                not self.state.remote_images.by_digest
                or not self.state.nodes
                or not self.state.needs_prepuller_refresh
            ):
                await asyncio.sleep(PREPULLER_INTERNAL_POLL_PERIOD)
            await self.prepull_images()
            self.state.update_prepuller_run_time()

    async def _wait_for_prepuller_close(self) -> None:
        accumulated_delay = 0.0
        increment = 1.0
        while (
            accumulated_delay < PREPULLER_PULL_TIMEOUT
            and self._prepull_scheduler is not None
        ):
            self.logger.warning(
                "Prepuller still running; total wait time "
                f"{accumulated_delay}s"
            )
            increment *= 1.5
            if accumulated_delay + increment > PREPULLER_PULL_TIMEOUT:
                increment = 0.1 + PREPULLER_PULL_TIMEOUT - accumulated_delay
            await asyncio.sleep(increment)
            accumulated_delay += increment
        if self._prepull_scheduler is not None:
            self.logger.error(
                f"Prepuller did not close within f{PREPULLER_PULL_TIMEOUT}s"
            )

    async def _docker_refresh(self) -> None:
        while self._stopping is False:
            await self.docker_client.refresh_if_needed()
            await asyncio.sleep(internal_poll_interval)

    async def _k8s_refresh(self) -> None:
        while self._stopping is False:
            await self.k8s_client.refresh_if_needed()
            await asyncio.sleep(internal_poll_interval)

    async def prepull_images(self) -> None:
        """Given a dict whose keys are the paths of images that need pulling
        and whose values are a list of names of nodes that need those images,
        start a pod from that image on each of those nodes.  This will have
        the effect of pulling the pod to each node.
        """

        required_pulls = self.arbitrator.get_required_prepull_images()
        # We can get more clever about this, but basically, we pull each image
        # in series, but spawn pods on all its nodes in parallel.
        # We would expect the pull to take about the same time for any node,
        # so this shouldn't waste too much time.
        for image in required_pulls:
            podname = image_to_podname(image)
            for node in required_pulls[image]:
                self.logger.debug(
                    f"Creating {self.namespace}/prepull-{podname}-{node}"
                )
                prepull_task = asyncio.create_task(
                    self.k8s_client.create_prepuller_pod(
                        name=f"prepull-{podname}-{node}",
                        namespace=self.namespace,
                        image=image,
                        node=node,
                    )
                )
                self._prepull_tasks.add(prepull_task)
                prepull_task.add_done_callback(self._prepull_tasks.discard)
            # Wait for pod_creation to complete on each node before going on
            # to the next image.
            await asyncio.gather(*self._prepull_tasks)
        # Refresh our view of the local node state
        await self.k8s_client.refresh_state_from_k8s()
