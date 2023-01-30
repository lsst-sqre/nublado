import pytest

from jupyterlabcontroller.factory import Context


@pytest.mark.asyncio
async def test_generate_user_lab_form(
    user_context: Context,
) -> None:
    px = user_context.prepuller_executor
    await px.k8s_client.refresh_state_from_k8s()
    await px.docker_client.refresh_state_from_docker_repo()
    r = user_context.form_manager.generate_user_lab_form()
    assert (
        r.find(
            '<option value="lighthouse.ceres/library/sketchbook:'
            'recommended@sha256:5678">'
        )
        != -1
    )
