from pathlib import Path

import pytest

from jupyterlabcontroller.factory import Context

from ..support.check_file import check_file


@pytest.mark.asyncio
async def test_generate_user_lab_form(
    user_context: Context, std_result_dir: Path
) -> None:
    px = user_context.prepuller_executor
    await px.k8s_client.refresh_state_from_k8s()
    await px.docker_client.refresh_state_from_docker_repo()
    r = user_context.form_manager.generate_user_lab_form()
    with open("/tmp/lab_form.txt", "w") as f:
        f.write(r)
    check_file(r, std_result_dir / "lab_form.txt")
