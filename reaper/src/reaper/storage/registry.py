"""Abstract superclass for container registry clients."""

import logging
from abc import abstractmethod
from pathlib import Path
from typing import cast

import semver
import structlog
from pydantic import HttpUrl

from ..config import RegistryAuth, RegistryConfig
from controller.models.domain.registryimage import (
    DEFAULT_LATEST_TAGS,
    RegistryImage,
    RegistryImageSpec,
    RegistryImageCollection,
    RegistryImageVersionClass,
)
from controller.models.domain.rsptag import (
    RSP_TYPENAMES,
    RSPImageTag,
    RSPImageTagCollection,
    RSPImageType,
)

DEFAULT_ALIAS_TAGS = {"recommended"}
DEFAULT_ALIAS_TAGS.update(set(DEFAULT_LATEST_TAGS))


class ContainerRegistryClient:
    """Collection of methods we expect any registry client to provide.

    Note that these are synchronous.  That's on purpose.  You can't really
    do anything until the scan_repo() (or debug_load_images()) completes, so
    there's no point making the generation of the initial map of images
    async.

    The actual image deletion could be done as async methods.  In
    fact, the initial run may take a long time if there are hundreds
    or thousands of images to delete.  However, after that, normally
    you're going to be running this daily, and you will be removing no
    more than a handful of images on any given run.  Whether that
    takes 45 seconds or 51 seconds (scanning the repository will be
    the longest-running task by far) is not particularly important.

    Registries generally rate-limit requests in any event, so blasting out a
    thousand DELETE requests in parallel is not going to work as well as you
    might hope.
    """

    @abstractmethod
    def authenticate(self, auth: RegistryAuth) -> None: ...

    @abstractmethod
    def scan_repo(self) -> None: ...

    @abstractmethod
    def debug_dump_images(self, outputfile: Path) -> None:
        """Write JSON of image map."""
        ...

    @abstractmethod
    def debug_load_images(self, inputfile: Path) -> None:
        """Read image map from JSON."""
        ...

    @abstractmethod
    def delete_images(self, inp: RegistryImageSpec) -> None:
        """Delete one or many images."""
        ...

    def __init__(self, cfg: RegistryConfig) -> None:
        # Because multiple inheritance makes running super().__init__() ugly,
        # we do the work in a method that is not likely to exist on a different
        # class.
        self._extract_registry_config(cfg)

    def _find_untagged_images(self) -> dict[str, RegistryImage]:
        # Return a map of untagged images by digest
        return {x.digest: x for x in self._images.values() if not x.tags}

    def _extract_registry_config(self, cfg: RegistryConfig) -> None:
        # Load the generic items from the registry config

        # Establish debugging and dry-run first.
        self._debug = cfg.debug
        self._dry_run = cfg.dry_run
        log_level = logging.DEBUG if self._debug else logging.INFO
        structlog.configure(
            wrapper_class=structlog.make_filtering_bound_logger(log_level)
        )
        # Common fields
        self._registry = str(cfg.registry)
        self._owner = cfg.owner
        self._repository = cfg.repository
        self._namespace = cfg.namespace
        self._image_version_class = cfg.image_version_class
        self._category = cfg.category
        name = self._registry + self._owner + "/"
        if self._namespace:
            name += self._namespace + "/"
        name += self._repository
        self.name = str(HttpUrl(name))
        # Set up logging
        self._logger = structlog.get_logger(self.name)
        self._logger.debug(f"Initialized logging for storage driver {self.name}")
        # Initialize empty image map
        self._images: dict[str, RegistryImage] = {}
        # Initialize empty categorized image map
        self.categorized_images = RegistryImageCollection()
        # Load inputs if supplied
        if cfg.input_file:
            self.debug_load_images(cfg.input_file)

    def categorize(self) -> None:
        """Run images through the tag interpreter; categorize and sort them."""
        if self._image_version_class == RegistryImageVersionClass.RSP:
            self._categorize_rsp()
        elif self._image_version_class == RegistryImageVersionClass.SEMVER:
            self._categorize_semver()
        self._categorize_untagged()

    def _categorize_rsp(self, aliases: set[str] = DEFAULT_ALIAS_TAGS) -> None:
        unsorted: list[RegistryImage] = list(self._images.values())
        # Add a single RSP tag to each image
        unsorted_tagged: list[RegistryImage] = []
        for img in unsorted:
            if not img.tags:
                # If the image has no tags, skip it.  It will be picked up
                # when we categorize the untagged images
                continue
            unsorted_tagged.append(img)
            raw_tags = list(img.tags)
            collection = RSPImageTagCollection.from_tag_names(
                raw_tags, aliases=aliases, cycle=None
            )
            rsp_image_tag = collection.best_tag()
            if rsp_image_tag is None:
                # Force an 'UNKNOWN' tag
                t_tag = raw_tags[0] if len(img.tags) > 0 else "unknown"
                rsp_image_tag = RSPImageTag.from_str(t_tag)
            img.rsp_image_tag = rsp_image_tag
            img.version_class = self._image_version_class

        categorized_unsorted = self._categorize_unsorted_rsp_images(unsorted_tagged)

        self.categorized_images.rsp = self._sort_categorized_rsp_images(
            categorized_unsorted
        )

    def _categorize_unsorted_rsp_images(
        self, unsorted: list[RegistryImage]
    ) -> dict[str, dict[str, RegistryImage]]:
        retval: dict[str, dict[str, RegistryImage]] = {}
        for category in RSP_TYPENAMES:
            retval[category] = {}
        for img in unsorted:
            for typ in RSPImageType:
                if (
                    img
                    and img.rsp_image_tag is not None
                    and img.rsp_image_tag.image_type == typ
                ):
                    key = typ.value.lower().replace(" ", "_")
                    retval[key][img.digest] = img
                    break
        return retval

    def _sort_categorized_rsp_images(
        self, categorized: dict[str, dict[str, RegistryImage]]
    ) -> dict[str, dict[str, RegistryImage]]:
        retval: dict[str, dict[str, RegistryImage]] = {}
        for key, imgs in categorized.items():
            # Sort the images and then insert them into a new dict.
            # Dicts now preserve insertion order.
            sorted_vals = sorted(imgs.values(), reverse=True)
            retval[key] = {x.digest: x for x in sorted_vals}
        return retval

    def _categorize_semver(self) -> None:
        unsorted = [x for x in list(self._images.values()) if x is not None]
        # Add a single semver tag to each image
        for img in unsorted:
            if img.tags:
                semvers = [semver.Version.parse(t) for t in img.tags]
                semvers.sort()
                if len(semvers) > 0:
                    img.semver_tag = semvers[0]
                else:
                    img.semver_tag = semver.Version.parse(f"0.0.0-{img.digest}")
            else:
                img.semver_tag = semver.Version.parse(f"0.0.0-{img.digest}")
        sorted_img = sorted(unsorted, reverse=True)
        self.categorized_images.semver = {x.digest: x for x in sorted_img}

    def _categorize_untagged(self) -> None:
        untagged = self._find_untagged_images()
        self.categorized_images.untagged = {
            x.digest: x for x in sorted(list(untagged.values()), reverse=True)
        }
        for img in self.categorized_images.untagged.values():
            img.version_class = RegistryImageVersionClass.UNTAGGED

    def _canonicalize_image_map(
        self, inp: RegistryImageSpec
    ) -> dict[str, RegistryImage]:
        """Take any of the ways of specifying images (dict of digest
        to RegistryImage, list of RegistryImages, list of digests, or
        single digest or RegistryImage) and return the dict mapping
        digest to RegistryImage.
        """
        # It's already in canonical form
        if isinstance(inp, dict):
            return inp

        # It's empty
        if not inp:
            return {}

        if isinstance(inp, list):
            item = inp[0]
            # List of digests
            if isinstance(item, str):
                # They better not be mixed.
                imgstrs = cast(list[str], inp)
                return {x: self._images[x] for x in imgstrs}
            # List of RegistryImages
            return {x.digest: x for x in inp}

        # Single items
        # Digest
        if isinstance(inp, str):
            return {inp: self._images[inp]}
        # RegistryImage
        return {inp.digest: inp}
