"""This is mostly stolen from kubespawner."""

import asyncio
import json
import time
from functools import partial
from typing import Any, Dict, Optional, Union

from fastapi import Depends
from kubernetes_asyncio import watch
from kubernetes_asyncio.client import api_client
from pydantic import BaseModel
from safir.dependencies.logger import logger_dependency
from structlog.stdlib import BoundLogger
from urllib3.exceptions import ReadTimeoutError

from ..config import config

__all__ = ["Watcher", "EventWatcher", "PodWatcher"]


class Watcher(BaseModel):
    kind: str
    namespace: str
    list_method_name: str = ""
    api_group_name: str = "CoreV1Api"
    request_timeout: int = config.k8s_request_timeout
    timeout_seconds: int = 10
    restart_seconds: int = 30
    logger: BoundLogger = Depends(logger_dependency)
    resources: Dict[str, Any]
    _stopping: bool = False
    _watch_task: Optional[asyncio.Task] = None
    _api: Optional[api_client] = None
    _first_load_future: asyncio.Future = asyncio.Future()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if not self.list_method_name:
            singular = {
                "endpoints": "endpoints",
                "events": "event",
                "ingresses": "ingress",
                "pods": "pod",
                "services": "service",
            }
            if self.kind in singular:
                self.list_method_name = "list_namespaced_{singular[self.kind]}"
        if not self.kind:
            raise RuntimeError("Reflector kind must be set!")
        if not self.list_method_name:
            raise RuntimeError("Reflector list_method_name must be set!")

    async def _list_and_update(self) -> str:
        """
        Update current list of resources by doing a full fetch.

        Overwrites all current resource info.
        """
        initial_resources = None
        kwargs = dict(
            namespace=self.namespace,
            _request_timeout=self.request_timeout,
            _preload_content=False,
        )
        list_method = getattr(self._api, self.list_method_name)
        initial_resources_raw = await list_method(**kwargs)
        initial_resources = json.loads(await initial_resources_raw.read())
        self.resources = {
            f'{p["metadata"]["namespace"]}/{p["metadata"]["name"]}': p
            for p in initial_resources["items"]
        }
        if not self._first_load_future.done():
            # signal that we've loaded our initial data at least once
            self._first_load_future.set_result(None)
        # return the resource version so we can hook up a watch
        return initial_resources["metadata"]["resourceVersion"]

    async def _watch_and_update(self) -> None:
        cur_delay: float = 0.1
        self.logger.info(
            f"watching for {self.kind} in namespace {self.namespace}"
        )
        while True:
            self.logger.debug(f"Connecting {self.kind} watcher")
            start = time.monotonic()
            w = watch.Watch()
            try:
                resource_version = await self._list_and_update()
                watch_args: Dict[str, Union[str, int]] = {
                    "resource_version": resource_version
                }
                if self.request_timeout:
                    # set network receive timeout
                    watch_args["_request_timeout"] = self.request_timeout
                if self.timeout_seconds:
                    # set watch timeout
                    watch_args["timeout_seconds"] = self.timeout_seconds
                # Calling the method with _preload_content=False is a
                # performance optimization making the Kubernetes client do
                # less work. See
                # https://github.com/jupyterhub/kubespawner/pull/424.
                method = partial(
                    getattr(self._api, self.list_method_name),
                    _preload_content=False,
                )
                async with w.stream(method, **watch_args) as stream:
                    async for watch_event in stream:
                        cur_delay = 0.1
                        resource = watch_event["raw_object"]
                        ref_key = "{}/{}".format(
                            resource["metadata"]["namespace"],
                            resource["metadata"]["name"],
                        )
                        if watch_event["type"] == "DELETED":
                            self.resources.pop(ref_key, None)
                        else:
                            self.resources[ref_key] = resource
                        if self._stopping:
                            self.logger.info(
                                f"{self.kind} watcher stopped: inner"
                            )
                            break
                        watch_duration = time.monotonic() - start
                        if watch_duration >= self.restart_seconds:
                            self.logger.debug(
                                f"Restarting {self.kind} watcher "
                                + f"after {watch_duration} seconds"
                            )
                            break

            except ReadTimeoutError:
                # network read time out, just continue and restart the watch
                # this could be due to a network problem or just low activity
                self.logger.warning(
                    f"Read timeout watching {self.kind}, reconnecting"
                )
                continue
            except asyncio.CancelledError:
                self.logger.debug(f"Cancelled watching {self.kind}")
                raise
            except Exception:
                cur_delay = cur_delay * 2
                if cur_delay > 30:
                    self.logger.exception(
                        "Watching resources never recovered, giving up"
                    )
                    return
                self.logger.exception(
                    f"Error when watching resources, retrying in {cur_delay}s"
                )
                await asyncio.sleep(cur_delay)
                continue
            else:
                # no events on watch, reconnect
                self.logger.debug(f"{self.kind} watcher timeout")
            finally:
                w.stop()
                if self._stopping:
                    self.logger.info(f"{self.kind} watcher stopped: outer")
                    break
        self.logger.warning(f"{self.kind} watcher finished")

    async def start(self) -> None:
        if self._watch_task and not self._watch_task.done():
            raise RuntimeError(
                f"Task watching for {self.kind} is already running"
            )
        try:
            await self._list_and_update()
        except Exception as e:
            self.logger.exception(f"Initial list of {self.kind} failed")
            if not self._first_load_future.done():
                # anyone awaiting our first load event should fail
                self._first_load_future.set_exception(e)
            raise
        self._watch_task = asyncio.create_task(self._watch_and_update())

    async def stop(self) -> None:
        """
        Cleanly shut down the watch task.
        """
        self._stopping = True
        if self._watch_task and not self._watch_task.done():
            # cancel the task, wait for it to complete
            self._watch_task.cancel()
            try:
                timeout = 5
                await asyncio.wait_for(self._watch_task, timeout)
            except asyncio.TimeoutError:
                # Raising the TimeoutError will cancel the task.
                self.logger.warning(
                    f"Watch task did not finish in {timeout}s; cancelled"
                )
        self._watch_task = None


class EventWatcher(Watcher):
    kind = "events"

    @property
    def events(self) -> Any:
        return sorted(
            self.resources.values(),
            key=lambda event: event["lastTimestamp"] or event["eventTime"],
        )


class PodWatcher(Watcher):
    kind = "pods"

    @property
    def pods(self) -> Any:
        return self.resources
