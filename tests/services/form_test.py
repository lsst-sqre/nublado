from pathlib import Path

import pytest

from jupyterlabcontroller.factory import Factory


@pytest.mark.asyncio
async def test_generate_user_lab_form(
    factory: Factory, std_result_dir: Path
) -> None:
    form_manager = factory.create_form_manager()
    r = form_manager.generate_user_lab_form()
    assert r == (std_result_dir / "lab_form.txt").read_text()
