import pytest

from jupyterlabcontroller.models.v1.domain.context import (
    ContextContainer,
    RequestContext,
)
from jupyterlabcontroller.services.form import FormManager


@pytest.mark.asyncio
async def test_generate_user_lab_form(
    request_context: RequestContext, context_container: ContextContainer
) -> None:
    fm: FormManager = FormManager(
        nublado=context_container, context=request_context
    )
    r = await fm.generate_user_lab_form()
    assert (
        r.find(
            '<option value="lighthouse.ceres/library/sketchbook:recommended">'
            "Recommended (Weekly 2077_43, Latest Weekly)</option>"
        )
        != -1
    )
