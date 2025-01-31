"""Provides reaping services for a Container Registry configuration."""

import datetime
import logging
import os
from copy import deepcopy

import structlog
from pydantic import SecretStr

from ..config import Config, RegistryAuth, RegistryConfig
from ..models.image import Image, ImageCollection, ImageVersionClass
from ..models.registry_category import RegistryCategory
from ..models.rsptag import RSP_TYPENAMES
from ..storage.dockerhub import DockerHubClient
from ..storage.gar import GARClient
from ..storage.ghcr import GhcrClient
from ..storage.registry import ContainerRegistryClient


class Reaper:
    """Provides the mechanism to implement an image retention policy."""

    def __init__(self, cfg: RegistryConfig) -> None:
        # Establish debugging and dry-run first.
        self._debug = cfg.debug
        self._dry_run = cfg.dry_run

        log_level = logging.DEBUG if self._debug else logging.INFO
        structlog.configure(
            wrapper_class=structlog.make_filtering_bound_logger(log_level)
        )
        # Common fields
        self._registry = cfg.registry
        self._owner = cfg.owner
        self._repository = cfg.repository
        self._namespace = cfg.namespace
        self._category = cfg.category
        self._category = cfg.category
        self._skip_tags = set(cfg.skip_tags)
        self._auth = RegistryAuth()
        self._image_version_class = cfg.image_version_class
        self._storage: ContainerRegistryClient | None = None
        match self._category:
            case RegistryCategory.DOCKERHUB:
                self._storage = DockerHubClient(cfg=cfg)
                self._auth.username = os.getenv("DOCKERHUB_USER")
                self._auth.password = SecretStr(os.getenv("DOCKERHUB_PASSWORD", ""))
            case RegistryCategory.GAR:
                self._storage = GARClient(cfg=cfg)
            case RegistryCategory.GHCR:
                self._auth.password = SecretStr(os.getenv("GHCR_TOKEN", ""))
                self._storage = GhcrClient(cfg=cfg)
            case _:
                raise NotImplementedError(
                    f"Storage driver for {self._category} not implemented yet"
                )
        self._keep_policy = cfg.keep
        self._plan: dict[str, Image] | None = None
        self._input_file = cfg.input_file
        self.name = self._storage.name
        # Set up logging
        self._logger = structlog.get_logger(f"reaper-{self.name}")
        self._logger.debug(f"Initialized logging for reaper {self.name}")

    def populate(self) -> None:
        if not self._storage:
            self._logger.warning("No storage driver defined.")
            return
        if not self._input_file:
            # We don't have preloaded data, so run a repo scan.
            self._storage.authenticate(self._auth)
            self._storage.scan_repo()
        self._storage.categorize()
        self._categorized = self._storage.categorized_images

    def plan(self) -> None:
        """Use the KeepPolicy to plan a set of images to delete."""
        if self._image_version_class == ImageVersionClass.RSP:
            self._plan = self._plan_rsp()
        elif self._image_version_class == ImageVersionClass.SEMVER:
            self._plan = self._plan_semver()
        else:
            self._plan = self._plan_untagged()

    def _plan_semver(self) -> dict[str, Image]:
        raise NotImplementedError("Semver image retention not yet implemented")

    def _plan_rsp(self) -> dict[str, Image]:
        retval: dict[str, Image] = {}
        kp = self._keep_policy.rsp
        if kp is None:
            return self._plan_untagged()
        for img_type in RSP_TYPENAMES:
            if img_type == "alias":
                # Alias should never be a resolved type.
                continue
            imgs = self._categorized.rsp[img_type]
            match img_type:
                case "release":
                    pol = kp.release
                case "weekly":
                    pol = kp.weekly
                case "daily":
                    pol = kp.daily
                case "release_candidate":
                    pol = kp.release_candidate
                case "experimental":
                    pol = kp.experimental
                case "unknown":
                    pol = kp.unknown
                case _:
                    raise NotImplementedError(
                        f"Don't know what to do with img_type '{img_type}'"
                    )

            if pol.number is None:
                if pol.age is not None:
                    retval.update(self._plan_age(pol.age, imgs=imgs))
            elif pol.number >= 0:
                retval.update(self._plan_number(keep_count=pol.number, imgs=imgs))
        retval.update(self._plan_untagged())
        return retval

    def _plan_untagged(self) -> dict[str, Image]:
        if self._keep_policy.untagged is None:
            return {}
        if self._keep_policy.untagged.number is None:
            if self._keep_policy.untagged.age is None:
                return {}
            return self._plan_age(
                self._keep_policy.untagged.age, imgs=self._categorized.untagged
            )
        if self._keep_policy.untagged.number < 0:
            return {}
        return self._plan_number(
            keep_count=self._keep_policy.untagged.number,
            imgs=self._categorized.untagged,
        )

    def _plan_age(
        self, age: datetime.timedelta, imgs: dict[str, Image]
    ) -> dict[str, Image]:
        retval: dict[str, Image] = {}
        now = datetime.datetime.now(tz=datetime.UTC)
        cutoff = now - age
        for dig, img in imgs.items():
            if img.tags & self._skip_tags:
                self._logger.info(
                    f"{img.tags} has members in {self._skip_tags}; notconsidering"
                )
                continue
            if img.date is None:
                self._logger.warning(f"Image '{dig}' has no date")
                continue
            if img.date < cutoff:
                retval[dig] = img
        return retval

    def _plan_number(self, keep_count: int, imgs: dict[str, Image]) -> dict[str, Image]:
        # Categorized images are already sorted
        # Filter out tags to skip
        filtered = {
            x.digest: x for x in list(imgs.values()) if not x.tags & self._skip_tags
        }
        return {x.digest: x for x in list(filtered.values())[keep_count:]}

    def report(self) -> None:
        """Report on images which would be purged by plan execution."""
        if self._plan is None:
            self._logger.warning(
                "No plan has been formulated and thus cannot be executed."
            )
            return
        headline = f"Images to purge for {self.name}:"
        print(headline)
        print("-" * len(headline))
        imgsplits = [str(x).split(" ", 2) for x in self._plan.values()]
        maxlen = max([len(x[0]) for x in imgsplits])
        for imgsplit in imgsplits:
            print(imgsplit[0], " " * (maxlen + 1 - len(imgsplit[0])), imgsplit[1])
        print("\n")

    def remaining(self) -> ImageCollection:
        """Return an ImageCollection containing those images which
        would remain after the results of a plan were removed during that
        plan's execution.
        """
        retval = deepcopy(self._categorized)
        if self._plan is None:
            self._logger.warning(
                "No plan has been formulated and thus cannot be executed."
            )
            return retval
        for dig in self._plan:
            for category in ("untagged", "semver"):
                immut = getattr(self._categorized, category)
                mut = getattr(retval, category)
                for img in immut:
                    if dig == img:
                        del mut[dig]
            immut = self._categorized.rsp
            mut = retval.rsp
            for nam in RSP_TYPENAMES:
                for img in immut[nam]:
                    if dig == img:
                        del mut[nam][dig]
        return retval

    def reap(self) -> None:
        if self._plan is None:
            self._logger.warning(
                "No plan has been formulated and thus cannot be executed."
            )
            return
        if self._storage is None:
            # No need to warn: self._plan wouldn't get populated without
            # a storage driver.
            return
        self._storage.delete_images(self._plan)
        self._plan = None


class BuckDharma:
    """Buck Dharma is in charge of all the Reapers."""

    def __init__(self, cfg: Config, *, interactive: bool = False) -> None:
        self.reaper: dict[str, Reaper] = {}
        for reg in cfg.registries:
            reaper = Reaper(reg)
            self.reaper[reaper.name] = reaper

    def populate(self) -> None:
        reapers = self.reaper.values()
        for reaper in reapers:
            reaper.populate()

    def plan(self) -> None:
        reapers = self.reaper.values()
        for reaper in reapers:
            reaper.plan()

    def report(self) -> None:
        reapers = self.reaper.values()
        for reaper in reapers:
            reaper.report()

    def reap(self) -> None:
        reapers = self.reaper.values()
        for reaper in reapers:
            reaper.reap()
