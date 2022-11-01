import asyncio
from collections.abc import AsyncGenerator
from typing import Any, Dict, Optional

from kubernetes_asyncio.client import ApiClient, ApiException
from kubernetes_asyncio.watch import Watch
from sse_starlette.sse import ServerSentEvent
from structlog.stdlib import BoundLogger

from ..models.v1.external.event import Event, EventMap, EventQueue


class EventManager:
    def __init__(self, logger: BoundLogger, events: EventMap) -> None:
        self.logger = logger
        self.events = events

    async def user_event_publisher(
        self,
        username: str,
    ) -> AsyncGenerator[ServerSentEvent, None]:
        try:
            while True:
                evs: Optional[EventQueue] = self.events.get(username)
                if evs:
                    for ev in evs:
                        if ev.sent:
                            continue
                        sse = ev.toSSE()
                        ev.sent = True
                        yield sse
                await asyncio.sleep(1.0)
        except asyncio.CancelledError as e:
            self.logger.info(f"User event stream disconnected for {username}")
            # Clean up?
            raise e


# Needs Adaptation to our use case
class KubernetesWatcher:
    """Watch for cluster-wide changes to a custom resource.

    Parameters
    ----------
    plural : `str`
        The plural for the custom resource for which to watch.
    api_client : ``kubernetes_asyncio.client.ApiClient``
        The Kubernetes client.
    queue : `EventQueue`
        The queue into which to put the events.
    logger : `structlog.stdlib.BoundLogger`
        Logger to use for messages.
    """

    def __init__(
        self,
        plural: str,
        api_client: ApiClient,
        queue: EventQueue,
        logger: BoundLogger,
    ) -> None:
        self._plural = plural
        self._queue = queue
        self._logger = logger
        self._api = api_client

    async def run(self) -> None:
        """Watch for changes to the configured custom object.

        This method is intended to be run as a background async task.  It will
        run forever, adding any custom object changes to the associated queue.
        """
        self._logger.debug("Starting Kubernetes watcher")
        consecutive_failures = 0
        watch_call = (
            self._api.list_cluster_custom_object,
            "gafaelfawr.lsst.io",
            "v1alpha1",
            self._plural,
        )
        while True:
            try:
                async with Watch().stream(*watch_call) as stream:
                    async for raw_event in stream:
                        event = self._parse_raw_event(raw_event)
                        if event:
                            self._queue.append(event)
                        consecutive_failures = 0
            except ApiException as e:
                # 410 status code just means our watch expired, and the
                # correct thing to do is quietly restart it.
                if e.status == 410:
                    continue
                msg = "ApiException from watch"
                consecutive_failures += 1
                if consecutive_failures > 10:
                    raise
                else:
                    self._logger.exception(msg, error=str(e))
                    msg = "Pausing 10s before attempting to continue"
                    self._logger.info()
                    await asyncio.sleep(10)

    def _parse_raw_event(self, raw_event: Dict[str, Any]) -> Optional[Event]:
        """Parse a raw event from the watch API.

        Returns
        -------
        event : `Event` or `None`
            An `Event` object if the event could be parsed, otherwise
           `None`.
        """
        try:
            return Event(
                event=raw_event["type"],
                data=raw_event["object"]
                #                namespace=raw_event["object"]["metadata"]["namespace"],
                #                generation=raw_event["object"]["metadata"]["generation"],
            )
        except KeyError:
            return None
