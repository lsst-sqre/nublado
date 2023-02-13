from pathlib import Path

import pytest

from jupyterlabcontroller.factory import Factory

from ..support.check_file import check_file


@pytest.mark.asyncio
async def test_generate_user_lab_form(
    factory: Factory, std_result_dir: Path
) -> None:
    form_manager = factory.create_form_manager()
    r = form_manager.generate_user_lab_form()
    with open("/tmp/lab_form.txt", "w") as f:
        f.write(r)
    check_file(r, std_result_dir / "lab_form.txt")
