"""Test for the alternate homedir schema."""

from __future__ import annotations

import pytest

from jupyterlabcontroller.factory import Factory
from jupyterlabcontroller.models.domain.rspimage import RSPImage
from jupyterlabcontroller.models.domain.rsptag import RSPImageTag
from jupyterlabcontroller.models.v1.lab import LabResources, ResourceQuantity

from ..settings import TestObjectFactory
from ..support.config import configure
from ..support.data import read_output_data


@pytest.mark.asyncio
async def test_homedir_schema_nss(obj_factory: TestObjectFactory) -> None:
    """Test building a passwd file with the alternate homedir layout."""
    _, user = obj_factory.get_user()
    config = configure("homedir-schema")
    expected_nss = read_output_data("homedir-schema", "nss.json")

    async with Factory.standalone(config) as factory:
        lm = factory.create_lab_manager()
        nss = lm.build_nss(user)
        assert nss == expected_nss


@pytest.mark.asyncio
async def test_homedir_schema_pod(obj_factory: TestObjectFactory) -> None:
    """Test building a pod spec with the alternate homedir layout and make
    sure `working_dir` is correctly set."""
    _, user = obj_factory.get_user()
    config = configure("homedir-schema")

    async with Factory.standalone(config) as factory:
        # We will construct image and resources fairly directly, rather than
        # going through the layers to get them 'legitimately'
        contents = obj_factory.test_objects["user_options"][0]["image_list"]
        tag = RSPImageTag.from_str(contents)
        registry, repo, rest = contents.split("/")
        ttag, digest = rest.split("@")
        image = RSPImage(
            registry=registry,
            repository=repo,
            digest=digest,
            size=None,
            aliases=set(),
            version=None,
            cycle=None,
            tag=ttag,
            image_type=tag.image_type,
            display_name=ttag,
        )
        resources = LabResources(
            limits=ResourceQuantity(cpu=1.0, memory=4294967296),
            requests=ResourceQuantity(cpu=0.25, memory=1073741824),
        )
        lm = factory.create_lab_manager()
        podspec = lm.build_pod_spec(user, resources, image)
        # The Pod spec isn't JSON-serializable, so we will just check the
        # field we care about rather than comparing the objects.
        assert podspec.containers[0].working_dir == "/home/r/rachel"
