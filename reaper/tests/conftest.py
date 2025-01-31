"""Test fixtures for registry image reaper."""

from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import yaml
from pydantic import HttpUrl

from rsp_reaper.config import KeepPolicy, RegistryConfig
from rsp_reaper.models.image import ImageVersionClass
from rsp_reaper.models.registry_category import RegistryCategory
from rsp_reaper.storage.dockerhub import DockerHubClient
from rsp_reaper.storage.gar import GARClient
from rsp_reaper.storage.ghcr import GhcrClient


@pytest.fixture
def gar_cfg() -> RegistryConfig:
    """Config for Google Artifact Registry."""
    input_file = Path(__file__).parent / "support" / "gar.contents.json"
    return RegistryConfig(
        category=RegistryCategory.GAR,
        registry=HttpUrl("https://us-central1-docker.pkg.dev"),
        owner="rubin-shared-services-71ec",
        namespace="sciplat",
        repository="sciplat-lab",
        keep=KeepPolicy(),
        image_version_class=ImageVersionClass.RSP,
        dry_run=True,
        debug=True,
        input_file=input_file,
    )


@pytest.fixture
def gar_client(gar_cfg: RegistryConfig) -> GARClient:
    """Client for Google Artifact Registry."""
    return GARClient(cfg=gar_cfg)


@pytest.fixture
def ghcr_cfg() -> RegistryConfig:
    """Config for GitHub Container Registry."""
    input_file = Path(__file__).parent / "support" / "ghcr.io.contents.json"
    return RegistryConfig(
        category=RegistryCategory.GHCR,
        registry=HttpUrl("https://ghcr.io"),
        owner="lsst-sqre",
        repository="sciplat-lab",
        keep=KeepPolicy(),
        image_version_class=ImageVersionClass.RSP,
        dry_run=True,
        debug=True,
        input_file=input_file,
    )


@pytest.fixture
def ghcr_client(ghcr_cfg: RegistryConfig) -> GhcrClient:
    """Client for GitHub Container Registry."""
    return GhcrClient(cfg=ghcr_cfg)


@pytest.fixture
def dockerhub_cfg() -> RegistryConfig:
    """Config for DockerHub."""
    input_file = Path(__file__).parent / "support" / "docker.io.contents.json"
    return RegistryConfig(
        category=RegistryCategory.DOCKERHUB,
        registry=HttpUrl("https://docker.io"),
        owner="lsstsqre",
        repository="sciplat-lab",
        keep=KeepPolicy(),
        image_version_class=ImageVersionClass.RSP,
        dry_run=True,
        debug=True,
        input_file=input_file,
    )


@pytest.fixture
def dockerhub_client(dockerhub_cfg: RegistryConfig) -> DockerHubClient:
    """Client for Docker Hub."""
    return DockerHubClient(cfg=dockerhub_cfg)


@pytest.fixture(scope="session")
def test_config() -> Iterator[Path]:
    """YAML configuration file."""
    with TemporaryDirectory() as td:
        new_config = Path(td) / "config.yaml"
        support_dir = Path(__file__).parent / "support"
        config = yaml.safe_load((support_dir / "config.yaml").read_text())
        config["registries"][0]["inputFile"] = str(
            support_dir / "ghcr.io.contents.json"
        )
        config["registries"][1]["inputFile"] = str(
            support_dir / "docker.io.contents.json"
        )
        new_config.write_text(yaml.dump(config))

        yield new_config
