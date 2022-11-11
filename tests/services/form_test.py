import pytest

from jupyterlabcontroller.models.v1.domain.context import Context
from jupyterlabcontroller.services.form import FormManager


@pytest.mark.asyncio
async def test_generate_user_lab_form(user_context: Context) -> None:
    fm: FormManager = FormManager(context=user_context)
    r = await fm.generate_user_lab_form()
    assert (
        r.find(
            '<option value="lighthouse.ceres/library/sketchbook:recommended">'
            "Recommended (Weekly 2077_43, Latest Weekly)</option>"
        )
        != -1
    )
