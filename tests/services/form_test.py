import pytest

from jupyterlabcontroller.models.context import Context
from jupyterlabcontroller.services.form import FormManager
from jupyterlabcontroller.services.prepull_executor import PrepullExecutor


@pytest.mark.asyncio
async def test_generate_user_lab_form(
    user_context: Context, prepull_executor: PrepullExecutor
) -> None:
    fm: FormManager = FormManager(
        context=user_context, prepull_executor=prepull_executor
    )
    r = await fm.generate_user_lab_form()
    assert (
        r.find(
            '<option value="lighthouse.ceres/library/sketchbook:recommended">'
            "Recommended (Weekly 2077_43, Latest Weekly)</option>"
        )
        != -1
    )
