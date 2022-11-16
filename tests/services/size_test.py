import pytest

from jupyterlabcontroller.config import Config
from jupyterlabcontroller.models.v1.lab import LabSize
from jupyterlabcontroller.services.size import SizeManager


@pytest.mark.asyncio
async def test_resources(config: Config) -> None:
    size_manager = SizeManager(sizes=config.lab.sizes)
    resource = size_manager.resources[LabSize("medium")]
    assert resource.limits.memory == 6442450944
    assert resource.limits.cpu == 2.0
    assert resource.requests.memory == 1610612736
    assert resource.requests.cpu == 0.5


@pytest.mark.asyncio
async def test_form(config: Config) -> None:
    size_manager = SizeManager(sizes=config.lab.sizes)
    formdata = size_manager.formdata
    assert len(formdata) == 3
    assert formdata[0].name == "Small"
    assert formdata[0].cpu == "1.0"
    assert formdata[0].memory == "3Gi"
