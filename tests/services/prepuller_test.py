from pathlib import Path

import pytest

from jupyterlabcontroller.factory import Context

from ..support.check_file import check_file


@pytest.mark.asyncio
async def test_get_menu_images(
    user_context: Context, std_result_dir: Path
) -> None:
    r = user_context.prepuller_arbitrator.get_menu_images()
    menu_str = f"{r}"
    check_file(menu_str, std_result_dir / "menu-images.txt")


@pytest.mark.asyncio
async def test_get_prepulls(
    user_context: Context, std_result_dir: Path
) -> None:
    px = user_context.prepuller_executor
    await px.k8s_client.refresh_state_from_k8s()
    await px.docker_client.refresh_state_from_docker_repo()
    r = user_context.prepuller_arbitrator.get_prepulls()
    prepull_str = f"{r}"
    check_file(prepull_str, std_result_dir / "prepulls.txt")
