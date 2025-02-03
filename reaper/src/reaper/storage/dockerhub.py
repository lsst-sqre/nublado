"""Minimalist function set of the Docker Hub API.

We must be able to list images, to get image digests and tags, and to
delete images.
"""

import datetime
import json
from pathlib import Path
from typing import cast

import httpx

from ..config import RegistryAuth, RegistryConfig
from controller.models.domain.registryimage import (
    DATEFMT,
    DEFAULT_LATEST_TAGS,
    RegistryCategory,
    RegistryImage,
    JSONRegistryImage,
    RegistryImageSpec,
)
from .registry import ContainerRegistryClient


class DockerHubClient(ContainerRegistryClient):
    """Client for talking to docker.io / hub.docker.com."""

    def __init__(self, cfg: RegistryConfig) -> None:
        if cfg.category.value != RegistryCategory.DOCKERHUB.value:
            raise ValueError(
                "DockerHub registry client must have value "
                f"'{RegistryCategory.DOCKERHUB.value}', not "
                f"'{cfg.category.value}'"
            )
        super()._extract_registry_config(cfg)
        self._http_client = httpx.Client()
        self._http_client.headers["content-type"] = "application/json"
        self._url = "https://hub.docker.com"

    def authenticate(self, i_auth: RegistryAuth) -> None:
        url = f"{self._url}/v2/users/login"
        auth = {
            "username": i_auth.username,
            "password": (i_auth.password.get_secret_value() if i_auth.password else ""),
        }
        r = self._http_client.post(url, json=auth)
        r.raise_for_status()  # Maybe we'll do 2fa sometime?
        self._logger.info(f"Authenticated '{i_auth.username}' to Docker Hub")
        self._http_client.headers["authorization"] = f"Bearer {r.json()['token']}"

    def scan_repo(self) -> None:
        next_page = (
            f"{self._url}/v2/namespaces/{self._owner}"
            f"/repositories/{self._repository}/tags"
        )
        page_size = 100
        count = 0
        params = {"page_size": page_size}
        while next_page:
            self._logger.debug(
                f"Requesting {self._owner}/{self._repository}: images "
                f"{count * page_size + 1}-{(count + 1) * page_size}"
            )
            if count > 0:
                params["page"] = count + 1
            r = self._http_client.get(next_page, params=params)
            r.raise_for_status()
            obj = r.json()
            next_page = obj["next"]
            results = obj["results"]
            for res in results:
                tag = res["name"]
                if tag in DEFAULT_LATEST_TAGS:
                    # ignore all of these: they're just clutter.
                    continue
                date = res["last_updated"]
                images = res["images"]
                for img in images:
                    digest = img["digest"]
                    self._upsert_image(digest, date, tag)
            count += 1
        self._logger.debug(f"Found {len(list(self._images.keys()))} images")

    def _upsert_image(self, digest: str, date: str, tag: str | None) -> None:
        dt = datetime.datetime.strptime(date, DATEFMT).astimezone(datetime.UTC)
        if self._images.get(digest, None) and tag:
            if self._images[digest].tags is None:  # empirically happens...
                self._images[digest].tags = set()
            self._images[digest].tags.add(tag)
        else:
            tags = {tag} if tag else set()
            self._images[digest] = RegistryImage(digest=digest, tags=tags, date=dt)

    def debug_dump_images(self, outputfile: Path) -> None:
        objs: dict[str, JSONRegistryImage] = {}
        for digest in self._images:
            img = self._images[digest]
            obj_img = img.to_dict()
            objs[digest] = obj_img
        dd: dict[str, dict[str, str] | dict[str, JSONRegistryImage]] = {
            "metadata": {"category": RegistryCategory.DOCKERHUB.value},
            "data": objs,
        }
        outputfile.write_text(json.dumps(dd, indent=2))

    def debug_load_images(self, inputfile: Path) -> None:
        inp = json.loads(inputfile.read_text())
        if inp["metadata"]["category"] != RegistryCategory.DOCKERHUB.value:
            raise ValueError(
                f"Dump is from {inp['metadata']['category']}, "
                f"not {RegistryCategory.DOCKERHUB.value}"
            )
        jsons = inp["data"]
        self._images = {}
        count = 0
        for digest in jsons:
            count += 1
            obj = cast(JSONRegistryImage, jsons[digest])
            self._images[digest] = RegistryImage.from_json(obj)
        self._logger.debug(f"Ingested {count} image{'s' if count > 1 else ''}")

    def delete_images(self, inp: RegistryImageSpec) -> None:
        """Delete images.

        https://distribution.github.io/distribution/spec/api/#deleting-an-image
        """
        images = self._canonicalize_image_map(inp)
        url = f"{self._url}/v2/{self._owner}/{self._repository}/manifests/"
        dry = " (not really)" if self._dry_run else ""
        count = 0
        for dig in images:
            ep = f"{url}{dig}"
            self._logger.debug(f"Deleting image {dig}{dry}")
            if not self._dry_run:
                r = self._http_client.delete(ep)
                r.raise_for_status()
            count += 1
        self._logger.info(f"Deleted {count} images{dry}")
        if not self._dry_run:
            self._plan = None
            for dig in images:
                if dig in self._images:
                    del self._images[dig]
