import pytest

from jupyterlabcontroller.models.context import Context


@pytest.mark.asyncio
async def test_generate_user_lab_form(
    user_context: Context,
) -> None:
    r = user_context.form_manager.generate_user_lab_form()
    assert (
        r.find(
            '<option value="lighthouse.ceres/library/sketchbook:'
            'recommended@sha256:5678">'
        )
        != -1
    )
