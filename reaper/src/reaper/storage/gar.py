"""Storage client for Google Artifact Registry."""

import datetime
import json
from collections.abc import Iterator
from pathlib import Path
from typing import cast

from google.cloud.artifactregistry_v1 import (
    ArtifactRegistryClient,
    BatchDeleteVersionsRequest,
    ListDockerImagesRequest,
)
from google.cloud.artifactregistry_v1.types import DockerImage
from google.protobuf.empty_pb2 import Empty

from ..config import RegistryAuth, RegistryConfig
from controller.models.domain.registryimage import (
    RegistryCategory,
    RegistryImageSpec,
    RegistryImage,
    JSONRegistryImage,
)
from .registry import ContainerRegistryClient


class GARClient(ContainerRegistryClient):
    """Client for Google Artifact Registry."""

    def __init__(self, cfg: RegistryConfig) -> None:
        if cfg.category.value != RegistryCategory.GAR.value:
            raise ValueError(
                "GAR registry client must have value "
                f"'{RegistryCategory.GAR.value}', not '{cfg.category.value}'"
            )
        self._category = cfg.category
        super()._extract_registry_config(cfg)
        gar_loc = "-docker.pkg.dev/"
        if not self._registry.endswith(gar_loc):
            raise ValueError(
                f"GAR registry location ('{self._registry}') must end with '{gar_loc}'"
            )
        location = self._registry[len("https://") : -(len(gar_loc))]

        self._parent: str = (
            f"projects/{self._owner}/locations/{location}"
            f"/repositories/{self._namespace}"
        )
        self._path: str = f"{self._owner}/{self._namespace}/{self._repository}"
        self._client: ArtifactRegistryClient = ArtifactRegistryClient()

    def authenticate(self, auth: RegistryAuth) -> None:
        """In production, we will use Workload Identity.

        For testing, we will use application default credentials.
        """

    def scan_repo(self) -> None:
        images: list[DockerImage] = []
        page_size = 100
        request = ListDockerImagesRequest(parent=self._parent, page_size=page_size)
        count = 0
        while True:
            self._logger.debug(
                f"Requesting {self._owner}/{self._namespace}/"
                f"{self._repository}: images "
                f"{count * page_size + 1}-{(count + 1) * page_size}"
            )
            resp = self._client.list_docker_images(request=request)
            images.extend(list(resp.docker_images))
            if not resp.next_page_token:
                break
            request = ListDockerImagesRequest(
                parent=self._parent,
                page_token=resp.next_page_token,
                page_size=page_size,
            )
            count += 1
        self._logger.debug(f"Found {len(images)} images")
        self._images = self._gar_to_images(images)

    def _gar_to_images(self, images: list[DockerImage]) -> dict[str, RegistryImage]:
        ret: dict[str, RegistryImage] = {}
        for img in images:
            ut = img.update_time
            micros = int(ut.nanosecond / 1000)
            dt = datetime.datetime(
                year=ut.year,
                month=ut.month,
                day=ut.day,
                hour=ut.hour,
                minute=ut.minute,
                second=ut.second,
                microsecond=micros,
                tzinfo=datetime.UTC,
            )
            tags = set(img.tags)
            repo_path, digest = img.name.split("@", 2)
            repo = repo_path.split("/")[-1]
            if repo != self._repository:
                self._logger.warning(f"Skipping image from repository {repo}")
                continue
            ret[digest] = RegistryImage(digest=digest, tags=tags, date=dt)
        return ret

    def debug_dump_images(self, outputfile: Path) -> None:
        objs: dict[str, JSONRegistryImage] = {}
        for digest in self._images:
            img = self._images[digest]
            obj_img = img.to_dict()
            objs[digest] = obj_img
        dd: dict[str, dict[str, str] | dict[str, JSONRegistryImage]] = {
            "metadata": {"category": RegistryCategory.GAR.value},
            "data": objs,
        }
        outputfile.write_text(json.dumps(dd, indent=2))

    def debug_load_images(self, inputfile: Path) -> None:
        inp = json.loads(inputfile.read_text())
        if inp["metadata"]["category"] != RegistryCategory.GAR.value:
            raise ValueError(
                f"Dump is from {inp['metadata']['category']}, "
                f"not {RegistryCategory.GAR.value}"
            )
        jsons = inp["data"]
        self._images = {}
        count = 0
        for digest in jsons:
            obj = cast(JSONRegistryImage, jsons[digest])
            self._images[digest] = RegistryImage.from_json(obj)
            count += 1
        self._logger.debug(f"Ingested {count} image{'s' if count > 1 else ''}")

    def _image_to_name(self, img: RegistryImage) -> str:
        return f"{self._parent}/packages/{self._repository}/versions/{img.digest}"

    def _chunk_images(
        self, inp: list[RegistryImage], n: int
    ) -> Iterator[list[RegistryImage]]:
        for i in range(0, len(inp), n):
            yield inp[i : i + n]

    def delete_images(self, inp: RegistryImageSpec) -> None:
        images = self._canonicalize_image_map(inp)
        digests = list(images.keys())
        names = [self._image_to_name(x) for x in list(images.values())]
        dry = " (not really)" if self._dry_run else ""
        count = len(digests)
        limit = 50
        # Empirical:
        #
        # google.api_core.exceptions.InvalidArgument: 400
        # A maximum of 50 versions are allowed per request
        for chunk in self._chunk_images(list(images.values()), limit):
            names = [self._image_to_name(x) for x in chunk]
            req = BatchDeleteVersionsRequest(
                parent=f"{self._parent}/packages/{self._repository}",
                names=names,
                validate_only=self._dry_run,
            )
            self._logger.debug(f"Request: {req}")
            self._logger.info(f"Deleting images {names}{dry}")
            operation = self._client.batch_delete_versions(request=req)
            resp = operation.result()
            if not isinstance(resp, Empty):
                e_str = "Something went wrong with batch deletion: {resp}"
                self._logger.error(e_str, response=resp)
                raise RuntimeError(e_str)
        self._logger.info(f"Deleted {count} images{dry}")
        if not self._dry_run:
            self._plan = None
            for dig in digests:
                if dig in self._images:
                    del self._images[dig]
            return
