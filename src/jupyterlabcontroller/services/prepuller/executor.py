"""The Executor, like State, should be a process singleton.  Its job is to
orchestrate the things the prepuller needs to do that actually call external
services (either Kubernetes or Docker).
"""

import asyncio
from typing import Optional

from aiojobs import Scheduler
from structlog.stdlib import BoundLogger

from ...constants import PREPULLER_INTERNAL_POLL_PERIOD, PREPULLER_PULL_TIMEOUT
from ...models.v1.prepuller import dashify
from ...models.v1.prepuller_config import PrepullerConfiguration
from ...storage.docker import DockerStorageClient
from ...storage.k8s import K8sStorageClient
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
            if self._prepull_scheduler is not None:
                self.logger.warning(
                    "Prepull scheduler already exists.  Presuming "
                    "earlier pull still in progress.  Not starting new pull."
                )
                return
            self._prepull_scheduler = Scheduler(
                close_timeout=PREPULLER_PULL_TIMEOUT
            )
            short_name = (image.split(":")[0]).split("/")[-1]
            tag = dashify((image.split(":")[1]).split("@")[0])
            for node in required_pulls[image]:
                await self._prepull_scheduler.spawn(
                    self.k8s_client.create_prepuller_pod(
                        name=f"prepull-{short_name}-{tag}",
                        namespace=self.namespace,
                        image=image,
                        node=node,
                    ),
                )
            self.logger.debug(
                f"Waiting up to {PREPULLER_PULL_TIMEOUT}s for prepuller "
                f"pod 'prepull-{short_name}-{tag}'."
            )
            await self._prepull_scheduler.close()
            # FIXME catch the TimeoutError if it happens
            self.logger.debug("Prepull_images complete.")
            self._prepull_scheduler = None
