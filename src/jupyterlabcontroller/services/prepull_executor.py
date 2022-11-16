"""Prepull images to nodes; requires the ability to spawn pods.
"""

import asyncio
from typing import Dict, List, Optional

from aiojobs import Scheduler

from ..config import Config
from ..constants import PREPULLER_POLL_INTERVAL, PREPULLER_PULL_TIMEOUT
from ..models.context import Context
from ..models.v1.lab import UserGroup, UserInfo
from ..storage.k8s import Container, PodSpec
from .prepuller import PrepullerManager


def need_some_context(
    context: Optional[Context] = None, config: Optional[Config] = None
) -> Context:
    if context is None:
        if config is None:
            raise RuntimeError("Config must be specified")
        context = Context.initialize(config=config)
        context.token = "token-of-affection"
        context.namespace = config.runtime.namespace_prefix
        context.user = UserInfo(
            username="prepuller",
            name="Prepuller User",
            uid=1000,
            gid=1000,
            groups=[
                UserGroup(
                    name="prepuller",
                    id=1000,
                )
            ],
        )
    if context is None:
        raise RuntimeError("Request context must be specified")
    return context


class PrepullExecutor:
    """This uses a PrepullerManager and adds the functionality to actually
    create prepulled pods as needed.

    Since we won't be called from a handler, we need to build our own
    nublado configuration context and request context.  We will have a
    config object already.  (The test for whether those contexts already
    exists is here to simplify testing, by allowing reuse of extant
    test fixtures.)

    The only piece of the request context we need is the uid, so for
    now we're just going to hardcode that to 1000 (which is ``lsst_lcl``
    in a sciplat-lab pod).

    It really doesn't matter: the only action we take is sleeping for five
    seconds, so not being in NSS doesn't make a difference, and "any non-zero
    uid" will work just fine.
    """

    def __init__(
        self,
        config: Optional[Config] = None,
        context: Optional[Context] = None,
    ) -> None:
        new_context = need_some_context(context, config)
        self._schedulers: Dict[str, Scheduler] = dict()
        self.context = new_context
        self._logger = self.context.logger
        self.manager = PrepullerManager(context=self.context)

    @classmethod
    def initialize(
        cls, config: Optional[Config] = None, context: Optional[Context] = None
    ) -> "PrepullExecutor":
        new_context = need_some_context(context, config)
        return cls(context=new_context)

    async def run(self) -> None:
        """
        Loop until we're told to stop.
        """

        if "main" not in self._schedulers or not self._schedulers["main"]:
            self._schedulers["main"] = Scheduler(close_timeout=0.1)

        self._logger.info("Starting prepull executor.")
        self.main_job = await self._schedulers["main"].spawn(
            self.primary_loop()
        )

    async def primary_loop(self) -> None:
        try:
            while True:
                await self.prepull_images()
                await self.idle()
        except asyncio.CancelledError:
            self._logger.info("Prepull executor interrupted.")
        except Exception as e:
            self._logger.error(f"{e}")
            raise
        self._logger.info("Shutting down prepull executor.")
        await self.aclose()

    async def idle(self) -> None:
        await asyncio.sleep(PREPULLER_POLL_INTERVAL)

    async def stop(self) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close any prepull schedulers."""
        if self._schedulers:
            for image in self._schedulers:
                if image == "main":
                    continue
                self._logger.warning(f"Terminating scheduler for {image}")
                await self._schedulers["main"].spawn(
                    self._schedulers[image].close()
                )
            for image in list(self._schedulers.keys()):
                del self._schedulers[image]
        if "main" in self._schedulers and self._schedulers["main"] is not None:
            self._logger.warning(
                "Terminating main prepuller executor scheduler"
            )
            await self._schedulers["main"].close()
            del self._schedulers["main"]

    async def create_prepuller_pod_spec(
        self, image: str, node: str
    ) -> PodSpec:
        shortname = image.split("/")[-1]
        if self.context.user is None:
            raise RuntimeError("User needed for pod creation")
        return PodSpec(
            containers=[
                Container(
                    name=f"prepull-{shortname}",
                    command=["/bin/sleep", "5"],
                    image=image,
                    working_dir="/tmp",
                )
            ],
            node_name=node,
        )

    async def prepull_images(self) -> None:
        """This is the method to identify everything that needs pulling, and
        spawns pods with those images on the nodes that need them.
        """

        status = await self.manager.get_prepulls()

        pending = status.images.pending

        required_pulls: Dict[str, List[str]] = dict()
        for img in pending:
            if img.missing is not None:
                for i in img.missing:
                    if i.eligible:
                        if img.path not in required_pulls:
                            required_pulls[img.path] = list()
                        required_pulls[img.path].append(i.name)
        self._logger.debug(f"Required pulls by node: {required_pulls}")
        timeout = PREPULLER_PULL_TIMEOUT
        # Parallelize across nodes but not across images
        for image in required_pulls:
            if image in self._schedulers:
                self._logger.warning(
                    f"Scheduler for image {image} already exists.  Presuming "
                    "earlier pull still in progress."
                )
                continue
            scheduler = Scheduler(close_timeout=timeout)
            self._schedulers[image] = scheduler
            tag = image.split(":")[1]
            for node in required_pulls[image]:
                await scheduler.spawn(
                    self.context.k8s_client.create_pod(
                        name=f"prepull-{tag}",
                        namespace=self.context.namespace,
                        pod=await self.create_prepuller_pod_spec(
                            image=image,
                            node=node,
                        ),
                    )
                )
            self._logger.debug(
                f"Waiting up to {timeout}s for prepuller pods {tag}."
            )
            await scheduler.close()
            del self._schedulers[image]
