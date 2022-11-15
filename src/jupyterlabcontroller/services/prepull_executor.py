"""Prepull images to nodes; requires the ability to spawn pods.
"""

import asyncio
from typing import Dict, List, Optional

from aiojobs import Scheduler

from ..config import Config
from ..constants import PREPULLER_POLL_INTERVAL, PREPULLER_PULL_TIMEOUT
from ..models.context import Context
from ..models.v1.lab import UserGroup, UserInfo
from ..models.v1.prepuller import PrepullerStatus
from ..storage.k8s import Container, PodSpec
from ..utils import get_namespace_prefix
from .prepuller import PrepullerManager


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
        self.schedulers: Dict[str, Scheduler] = {}

        if context is None:
            if config is None:
                raise RuntimeError("Config must be specified")
            context = Context.initialize(config=config)
            context.token = "token-of-affection"
            context.namespace = get_namespace_prefix()
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
        self.context = context
        self.logger = self.context.logger
        self.manager = PrepullerManager(context=context)

    async def run(self) -> None:
        """
        Loop until we're told to stop.
        """

        if "main" not in self.schedulers or not self.schedulers["main"]:
            self.schedulers["main"] = Scheduler(close_timeout=0.1)

        self.logger.info("Starting prepull executor.")
        self.main_job = await self.schedulers["main"].spawn(
            self.primary_loop()
        )

    async def primary_loop(self) -> None:
        try:
            while True:
                await self.prepull_images()
                await self.idle()
        except asyncio.CancelledError:
            self.logger.info("Prepull executor interrupted.")
        except Exception as e:
            self.logger.error(f"{e}")
            raise
        self.logger.info("Shutting down prepull executor.")
        await self.aclose()

    async def idle(self) -> None:
        await asyncio.sleep(PREPULLER_POLL_INTERVAL)

    async def stop(self) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close any prepull schedulers."""
        if self.schedulers:
            for image in self.schedulers:
                if image == "main":
                    continue
                self.logger.warning(f"Terminating scheduler for {image}")
                await self.schedulers["main"].spawn(
                    self.schedulers[image].close()
                )
            for image in list(self.schedulers.keys()):
                del self.schedulers[image]
        if "main" in self.schedulers and self.schedulers["main"] is not None:
            self.logger.warning(
                "Terminating main prepuller executor scheduler"
            )
            await self.schedulers["main"].close()
            del self.schedulers["main"]

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
        spawns pods with those images on the node that needs them.
        """

        status: PrepullerStatus = await self.manager.get_prepulls()

        pending = status.images.pending

        required_pulls: Dict[str, List[str]] = {}
        for img in pending:
            for i in img.missing:
                if i.eligible:
                    if img.path not in required_pulls:
                        required_pulls[img.path] = []
                    required_pulls[img.path].append(i.name)
        self.logger.debug(f"Required pulls by node: {required_pulls}")
        timeout = PREPULLER_PULL_TIMEOUT
        # Parallelize across nodes but not across images
        for image in required_pulls:
            if image in self.schedulers:
                self.logger.warning(
                    f"Scheduler for image {image} already exists.  Presuming "
                    "earlier pull still in progress."
                )
                continue
            scheduler = Scheduler(close_timeout=timeout)
            self.schedulers[image] = scheduler
            tag = image.split(":")[1]
            for node in required_pulls[image]:
                await scheduler.spawn(
                    self.context.k8s_client.create_pod(
                        name=f"prepull-{tag}",
                        namespace=get_namespace_prefix(),
                        pod=await self.create_prepuller_pod_spec(
                            image=image,
                            node=node,
                        ),
                    )
                )
            self.logger.debug(
                f"Waiting up to {timeout}s for prepuller pods {tag}."
            )
            await scheduler.close()
            del self.schedulers[image]
