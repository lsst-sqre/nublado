"""Tests for the :command:`nublado images` CLI."""

import os
from typing import Any

import pytest
import respx
from click.testing import CliRunner
from google.cloud.artifactregistry_v1 import DockerImage

from nublado.cli import main
from nublado.models.docker import DockerCredentialStore
from nublado.models.images import DockerSource, RSPImageTagCollection

from ..support.data import NubladoData
from ..support.docker import register_mock_docker
from ..support.gar import MockArtifactRegistry


@pytest.fixture
def mock_gar_images(
    data: NubladoData, mock_gar: MockArtifactRegistry
) -> list[dict[str, Any]]:
    known_images = data.read_json("registry/gar")
    mock_gar.add_images_for_test(DockerImage(**i) for i in known_images)
    return known_images


def test_list_docker(data: NubladoData, respx_mock: respx.Router) -> None:
    config_path = data.path("images/docker.yaml")
    credential_path = data.path("registry/docker-creds.json")
    credential_store = DockerCredentialStore.from_path(credential_path)
    source = data.read_pydantic(DockerSource, "storage/docker-source")
    tag_names = [
        "w_2021_22",
        "w_2021_22-amd64",
        "w_2021_21",
        "w_2021_21-arm64",
        "w_2021_21-amd64",
        "d_2021_06_15",
        "d_2021_06_14-amd64",
    ]
    tags = {t: "sha256:" + os.urandom(32).hex() for t in tag_names}
    tag_names.append("recommended")
    tags["recommended"] = tags["w_2021_21"]
    register_mock_docker(respx_mock, source, credential_store, tags=tags)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["images", "list", "-c", str(config_path), "-a", str(credential_path)],
        catch_exceptions=False,
    )
    assert result.output == "\n".join(tag_names) + "\n"
    assert result.exit_code == 0


def test_list_gar(
    data: NubladoData, mock_gar_images: list[dict[str, Any]]
) -> None:
    config_path = data.path("images/gar.yaml")

    # Determine the expected tag list. Alias information is discarded by the
    # current list implementation, so alias tags are treated as unknown and
    # sorted last.
    unsorted_tags = []
    for image in mock_gar_images:
        if "sciplat-lab" not in image["name"]:
            continue
        unsorted_tags.extend(image["tags"])
    collection = RSPImageTagCollection.from_tag_names(unsorted_tags)
    tags = [t.tag for t in collection.all_tags(hide_arch_specific=False)]

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["images", "list", "-c", str(config_path)],
        catch_exceptions=False,
    )
    assert result.output == "\n".join(tags) + "\n"
    assert result.exit_code == 0


def test_prune_docker(data: NubladoData, respx_mock: respx.Router) -> None:
    config_path = data.path("images/docker.yaml")
    credential_path = data.path("registry/docker-creds.json")
    credential_store = DockerCredentialStore.from_path(credential_path)
    source = data.read_pydantic(DockerSource, "storage/docker-source")
    tag_names = [
        "w_2021_22",
        "w_2021_22-amd64",
        "w_2021_21",
        "w_2021_21-arm64",
    ]
    tags = {t: "sha256:" + os.urandom(32).hex() for t in tag_names}
    register_mock_docker(respx_mock, source, credential_store, tags=tags)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "images",
            "prune",
            "-n",
            "-c",
            str(config_path),
            "-a",
            str(credential_path),
        ],
        catch_exceptions=False,
    )
    expected = "Would delete images:\n  w_2021_21\n  w_2021_21-arm64\n"
    assert result.output == expected
    assert result.exit_code == 0

    result = runner.invoke(
        main,
        ["images", "list", "-c", str(config_path), "-a", str(credential_path)],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "w_2021_21" in result.output

    result = runner.invoke(
        main,
        [
            "images",
            "prune",
            "-c",
            str(config_path),
            "-a",
            str(credential_path),
        ],
        catch_exceptions=False,
    )
    assert result.output == "Deleted images:\n  w_2021_21\n  w_2021_21-arm64\n"
    assert result.exit_code == 0

    result = runner.invoke(
        main,
        ["images", "list", "-c", str(config_path), "-a", str(credential_path)],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "w_2021_21" not in result.output


@pytest.mark.usefixtures("mock_gar_images")
def test_prune_gar(data: NubladoData) -> None:
    config_path = data.path("images/gar.yaml")
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["images", "prune", "-n", "-c", str(config_path)],
        catch_exceptions=False,
    )
    assert result.output == "Would delete images:\n  w_2077_42\n  w_2077_41\n"
    assert result.exit_code == 0

    result = runner.invoke(
        main,
        ["images", "list", "-c", str(config_path)],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "w_2077_42" in result.output

    result = runner.invoke(
        main,
        ["images", "prune", "-c", str(config_path)],
        catch_exceptions=False,
    )
    assert result.output == "Deleted images:\n  w_2077_42\n  w_2077_41\n"
    assert result.exit_code == 0

    result = runner.invoke(
        main,
        ["images", "list", "-c", str(config_path)],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "w_2077_42" not in result.output
