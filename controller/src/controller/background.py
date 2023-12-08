"""Nublado controller background processing."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta

from aiojobs import Scheduler
from safir.datetime import current_datetime
from safir.slack.webhook import SlackWebhookClient
from structlog.stdlib import BoundLogger

from .constants import (
    FILE_SERVER_RECONCILE_INTERVAL,
    IMAGE_REFRESH_INTERVAL,
    LAB_RECONCILE_INTERVAL,
)
from .services.fileserver import FileserverManager
from .services.image import ImageService
from .services.lab import LabManager
from .services.prepuller import Prepuller

__all__ = ["BackgroundTaskManager"]


class BackgroundTaskManager:
    """Manage Nublado controller background tasks.

    While the Nublado controller is running, it needs to perform several
    periodic or continuous background tasks, namely:

    #. Refresh the list of available remote images and local cached images.
    #. Prepull images to all eligible nodes.
    #. Reconcile Kubernetes lab state with internal data structures.
    #. Reap tasks that were monitoring lab spawning or deletion.
    #. Watch file servers for changes in pod status (startup or timeout).
    #. Reconcile Kubernetes file server state with internal data structures.

    This class manages all of these background tasks including, where
    relevant, their schedules. It only does the task management; all of the
    work of these tasks is done by methods on the underlying service objects.

    This class is created during startup and tracked as part of the
    `~controller.factory.ProcessContext`.

    Parameters
    ----------
    image_service
        Image service.
    prepuller
        Prepuller service.
    lab_manager
        Lab management service.
    fileserver_manager
        File server management service.
    slack_client
        Optional Slack webhook client for alerts.
    logger
        Logger to use.
    """

    def __init__(
        self,
        *,
        image_service: ImageService,
        prepuller: Prepuller,
        lab_manager: LabManager,
        fileserver_manager: FileserverManager | None,
        slack_client: SlackWebhookClient | None,
        logger: BoundLogger,
    ) -> None:
        self._image_service = image_service
        self._prepuller = prepuller
        self._lab_manager = lab_manager
        self._fileserver_manager = fileserver_manager
        self._slack = slack_client
        self._logger = logger

        self._scheduler: Scheduler | None = None

    async def start(self) -> None:
        """Start all background tasks.

        Intended to be called during Nublado controller startup. Several of
        the background tasks are run in the foreground first to ensure
        internal state is valid before starting to serve requests.
        """
        if self._scheduler:
            msg = "Background tasks already running, cannot start"
            self._logger.warning(msg)
            return
        self._scheduler = Scheduler()

        # Run some of the tasks in the foreground first to ensure internal
        # data is consistent after startup. All of them can run in parallel.
        async with asyncio.TaskGroup() as tg:
            self._logger.info("Populating internal state")
            tg.create_task(self._image_service.refresh())
            tg.create_task(self._lab_manager.reconcile())
            if self._fileserver_manager:
                tg.create_task(self._fileserver_manager.reconcile())

        # Now, start all of the tasks in the background.
        coros = [
            self._loop(
                self._image_service.refresh,
                IMAGE_REFRESH_INTERVAL,
                "refreshing image data",
            ),
            self._prepull_loop(),
            self._loop(
                self._lab_manager.reconcile,
                LAB_RECONCILE_INTERVAL,
                "reconciling lab state",
            ),
            self._lab_manager.reap_spawners(),
        ]
        if self._fileserver_manager:
            coros.append(
                self._loop(
                    self._fileserver_manager.reconcile,
                    FILE_SERVER_RECONCILE_INTERVAL,
                    "reconciling file server state",
                )
            )
            coros.append(self._fileserver_manager.watch_servers())
        self._logger.info("Starting background tasks")
        for coro in coros:
            await self._scheduler.spawn(coro)

    async def stop(self) -> None:
        """Stop the background tasks."""
        if not self._scheduler:
            msg = "Background tasks were already stopped"
            self._logger.warning(msg)
            return
        self._logger.info("Stopping background tasks")
        await self._scheduler.close()
        self._scheduler = None
        await self._lab_manager.stop_monitor_tasks()

    async def _loop(
        self,
        call: Callable[[], Awaitable[None]],
        interval: timedelta,
        description: str,
    ) -> None:
        """Wrap a coroutine in a periodic scheduling loop.

        The provided coroutine is run on every interval. This method always
        delays by the interval first before running the coroutine for the
        first time.

        Parameters
        ----------
        call
            Async function to run repeatedly.
        interval
            Scheduling interval to use.
        description
            Description of the background task for error reporting.
        """
        while True:
            start = current_datetime(microseconds=True)
            try:
                await call()
            except Exception as e:
                # On failure, log the exception but otherwise continue as
                # normal, including the delay. This will provide some time for
                # whatever the problem was to be resolved.
                elapsed = current_datetime(microseconds=True) - start
                msg = f"Uncaught exception {description}"
                self._logger.exception(msg, delay=elapsed.total_seconds)
                if self._slack:
                    await self._slack.post_uncaught_exception(e)
            delay = interval - (current_datetime(microseconds=True) - start)
            if delay.total_seconds() < 1:
                msg = f"{description.capitalize()} is running continuously"
                self._logger.warning(msg)
            else:
                await asyncio.sleep(delay.total_seconds())

    async def _prepull_loop(self) -> None:
        """Execute the prepuller in an infinite loop.

        The prepuller loop uses an `asyncio.Event` set by the image service to
        decide when to run instead of a simple interval. This ensures the
        prepuller runs immediately after a possible image list update.
        """
        while True:
            try:
                await self._image_service.prepuller_wait()
                await self._prepuller.prepull_images()
            except Exception as e:
                self._logger.exception("Uncaught exception prepulling images")
                if self._slack:
                    await self._slack.post_uncaught_exception(e)
                pause = IMAGE_REFRESH_INTERVAL.total_seconds()
                self._logger.warning("Pausing failed prepuller for {pause}s")
                await asyncio.sleep(pause)
