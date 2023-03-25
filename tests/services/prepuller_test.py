import json
from pathlib import Path

import pytest

from jupyterlabcontroller.factory import Factory


@pytest.mark.asyncio
async def test_get_prepulls(factory: Factory, std_result_dir: Path) -> None:
    with (std_result_dir / "prepulls.json").open("r") as f:
        expected = json.load(f)
    r = factory.image_service.prepull_status()
    assert r.dict() == expected
