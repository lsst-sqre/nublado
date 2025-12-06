"""Tests for the Nublado client."""

from __future__ import annotations

from contextlib import aclosing
from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import ANY
from uuid import UUID

import pytest
from safir.datetime import format_datetime_for_logging
from safir.slack.blockkit import SlackCodeBlock, SlackTextBlock, SlackTextField

from rubin.nublado.client import (
    CodeContext,
    MockJupyter,
    MockJupyterAction,
    MockJupyterState,
    NotebookExecutionResult,
    NubladoClient,
    NubladoExecutionError,
    NubladoImage,
    NubladoImageByClass,
    NubladoImageByReference,
    NubladoImageByTag,
    NubladoImageClass,
    NubladoImageSize,
    NubladoRedirectError,
    NubladoSpawnError,
    NubladoWebError,
)

from .support.data import read_test_data


@pytest.mark.asyncio
async def test_hub_flow(
    client: NubladoClient, username: str, mock_jupyter: MockJupyter
) -> None:
    """Check that the Hub operations work as expected."""
    assert mock_jupyter.get_state(username) == MockJupyterState.LOGGED_OUT

    # Must authenticate first.
    with pytest.raises(AssertionError):
        assert await client.is_lab_stopped()

    await client.auth_to_hub()
    assert mock_jupyter.get_state(username) == MockJupyterState.LOGGED_IN
    assert await client.is_lab_stopped()

    # Simulate spawn.
    await client.spawn_lab(NubladoImageByClass())
    assert mock_jupyter.get_last_spawn_form(username) == {
        "image_class": "recommended",
        "size": "Large",
    }
    assert mock_jupyter.get_state(username) == MockJupyterState.SPAWN_PENDING

    # Watch the progress meter.
    progress = -1
    async with aclosing(client.watch_spawn_progress()) as spawn_progress:
        async for message in spawn_progress:
            if message.ready:
                break
            assert message.progress > progress
            progress = message.progress

    # Lab should now be running. Execute some code.
    assert mock_jupyter.get_state(username) == MockJupyterState.LAB_RUNNING
    assert not await client.is_lab_stopped()
    assert mock_jupyter.get_session(username) is None
    async with client.lab_session() as session:
        result = await session.run_python("print(2+2)")
        assert result.strip() == "4"

        # Check the parameters of the session.
        session_data = mock_jupyter.get_session(username)
        assert session_data
        assert session_data.kernel_name == "lsst"
        assert session_data.name == "(no notebook)"
        assert UUID(session_data.path)
        assert session_data.type == "console"

    # Create a session with a notebook name.
    async with client.lab_session(
        "notebook.ipynb", kernel_name="custom"
    ) as session:
        result = await session.run_python("print(3+2)")
        assert result.strip() == "5"

        # Check the parameters of the session.
        session_data = mock_jupyter.get_session(username)
        assert session_data
        assert session_data.kernel_name == "custom"
        assert session_data.name == "notebook.ipynb"
        assert session_data.path == "notebook.ipynb"
        assert session_data.type == "notebook"

    # It's possible to get the spawn progress again while the lab is running.
    async with aclosing(client.watch_spawn_progress()) as spawn_progress:
        async for message in spawn_progress:
            if message.ready:
                break

    # Stop the lab
    await client.stop_lab()
    assert await client.is_lab_stopped()
    assert mock_jupyter.get_state(username) == MockJupyterState.LOGGED_IN


@pytest.mark.asyncio
async def test_run_notebook(
    client: NubladoClient, username: str, mock_jupyter: MockJupyter
) -> None:
    notebook = read_test_data("faux-input-nb")
    output = read_test_data("faux-output-nb")
    expected = NotebookExecutionResult(notebook=output)
    mock_jupyter.register_notebook_result(notebook, expected)

    await client.auth_to_hub()
    await client.spawn_lab(NubladoImageByClass())
    await client.wait_for_spawn()

    result = await client.run_notebook(notebook)
    assert result == expected
    assert mock_jupyter.get_last_notebook_kernel(username) is None

    result = await client.run_notebook(notebook, kernel_name="Custom")
    assert result == expected
    assert mock_jupyter.get_last_notebook_kernel(username) == "Custom"


@dataclass
class FormTestCase:
    image: NubladoImage
    form: dict[str, str]


@pytest.mark.asyncio
async def test_lab_form(
    client: NubladoClient, username: str, mock_jupyter: MockJupyter
) -> None:
    await client.auth_to_hub()

    # List of NubladoImage objects to pass in to spawn and the expected
    # submitted lab form.
    test_cases = [
        FormTestCase(
            image=NubladoImageByReference(
                reference="example/lab:some-tag", debug=True
            ),
            form={
                "image_list": "example/lab:some-tag",
                "size": "Large",
                "enable_debug": "true",
            },
        ),
        FormTestCase(
            image=NubladoImageByTag(tag="some-tag"),
            form={"image_tag": "some-tag", "size": "Large"},
        ),
        FormTestCase(
            image=NubladoImageByClass(),
            form={"image_class": "recommended", "size": "Large"},
        ),
        FormTestCase(
            image=NubladoImageByClass(
                image_class=NubladoImageClass.LATEST_RELEASE,
                size=NubladoImageSize.Small,
                debug=True,
            ),
            form={
                "image_class": "latest-release",
                "size": "Small",
                "enable_debug": "true",
            },
        ),
    ]

    # For each of the test cases, spawn a lab and check the lab form.
    for test_case in test_cases:
        await client.spawn_lab(test_case.image)
        assert mock_jupyter.get_last_spawn_form(username) == test_case.form
        await client.wait_for_spawn()
        await client.stop_lab()


def check_web_exception(
    exc: NubladoWebError,
    *,
    start: datetime,
    username: str,
    method: str,
    route: str,
) -> None:
    """Check that a web exception has the correct components."""
    assert route in exc.message
    assert route in str(exc)
    assert exc.method == method
    assert exc.started_at
    assert exc.started_at >= start
    assert exc.failed_at >= exc.started_at
    assert exc.url
    assert route in exc.url
    assert exc.status == 500

    slack = exc.to_slack()
    assert route in slack.message

    sentry = exc.to_sentry()
    expected = format_datetime_for_logging(exc.started_at)
    assert sentry.contexts["info"]["started_at"] == expected


@pytest.mark.asyncio
async def test_failures(
    client: NubladoClient, username: str, mock_jupyter: MockJupyter
) -> None:
    start = datetime.now(tz=UTC)
    notebook = read_test_data("faux-input-nb")

    mock_jupyter.fail_on(username, MockJupyterAction.LOGIN)
    with pytest.raises(NubladoWebError) as exc_info:
        await client.auth_to_hub()
    check_web_exception(
        exc_info.value,
        start=start,
        username=username,
        method="GET",
        route="hub/home",
    )

    mock_jupyter.fail_on(username, MockJupyterAction.SPAWN)
    await client.auth_to_hub()
    with pytest.raises(NubladoWebError) as exc_info:
        await client.spawn_lab(NubladoImageByClass())
    check_web_exception(
        exc_info.value,
        start=start,
        username=username,
        method="POST",
        route="hub/spawn",
    )

    mock_jupyter.fail_on(username, MockJupyterAction.SPAWN_PENDING)
    with pytest.raises(NubladoWebError) as exc_info:
        await client.spawn_lab(NubladoImageByClass())
    check_web_exception(
        exc_info.value,
        start=start,
        username=username,
        method="GET",
        route=f"hub/spawn-pending/{username}",
    )

    await client.stop_lab()
    mock_jupyter.fail_on(username, MockJupyterAction.USER)
    await client.spawn_lab(NubladoImageByClass())
    await client.wait_for_spawn()
    with pytest.raises(NubladoWebError) as exc_info:
        await client.is_lab_stopped()
    check_web_exception(
        exc_info.value,
        start=start,
        username=username,
        method="GET",
        route=f"hub/api/users/{username}",
    )

    mock_jupyter.fail_on(username, MockJupyterAction.LAB)
    assert not await client.is_lab_stopped()
    with pytest.raises(NubladoWebError) as exc_info:
        await client.auth_to_lab()
    check_web_exception(
        exc_info.value,
        start=start,
        username=username,
        method="GET",
        route=f"user/{username}/lab",
    )

    mock_jupyter.fail_on(username, MockJupyterAction.RUN_NOTEBOOK)
    await client.auth_to_lab()
    with pytest.raises(NubladoWebError) as exc_info:
        await client.run_notebook(notebook)
    check_web_exception(
        exc_info.value,
        start=start,
        username=username,
        method="POST",
        route=f"user/{username}/rubin/execution",
    )

    mock_jupyter.fail_on(username, MockJupyterAction.CREATE_SESSION)
    with pytest.raises(NubladoWebError) as exc_info:
        async with client.lab_session():
            pass
    check_web_exception(
        exc_info.value,
        start=start,
        username=username,
        method="POST",
        route=f"user/{username}/api/sessions",
    )

    mock_jupyter.fail_on(username, MockJupyterAction.DELETE_SESSION)
    with pytest.raises(NubladoWebError) as exc_info:
        async with client.lab_session():
            pass
    check_web_exception(
        exc_info.value,
        start=start,
        username=username,
        method="DELETE",
        route=f"user/{username}/api/sessions",
    )

    mock_jupyter.fail_on(username, MockJupyterAction.DELETE_LAB)
    with pytest.raises(NubladoWebError) as exc_info:
        await client.stop_lab()
    check_web_exception(
        exc_info.value,
        start=start,
        username=username,
        method="DELETE",
        route=f"hub/api/users/{username}/server",
    )


@pytest.mark.asyncio
async def test_spawn_failure(
    client: NubladoClient, username: str, mock_jupyter: MockJupyter
) -> None:
    mock_jupyter.fail_on(username, MockJupyterAction.PROGRESS)

    await client.auth_to_hub()
    await client.spawn_lab(NubladoImageByClass())
    async with aclosing(client.watch_spawn_progress()) as spawn_progress:
        async for message in spawn_progress:
            if message.ready:
                break
    assert not message.ready

    await client.stop_lab()
    await client.spawn_lab(NubladoImageByClass())
    with pytest.raises(NubladoSpawnError) as exc_info:
        await client.wait_for_spawn()
    assert "Spawn failed!" in exc_info.value.message
    assert "Spawn failed!" in "\n".join(exc_info.value.log)
    info = exc_info.value.to_sentry()
    assert "Spawn failed!" in info.attachments["spawn_log.txt"]


@pytest.mark.asyncio
async def test_redirect_loop(
    client: NubladoClient, username: str, mock_jupyter: MockJupyter
) -> None:
    mock_jupyter.set_redirect_loop(enabled=True)
    with pytest.raises(NubladoRedirectError) as exc_info:
        await client.auth_to_hub()
    assert "/hub/home" in exc_info.value.message

    # The errors from httpx-sse are unfortunately not great and will complain
    # about the Content-Type instead of showing the actual error. This may
    # require upstream fixes to get better error reports.
    mock_jupyter.set_redirect_loop(enabled=False)
    await client.auth_to_hub()
    await client.spawn_lab(NubladoImageByClass())
    mock_jupyter.set_redirect_loop(enabled=True)
    with pytest.raises(NubladoWebError):
        await client.wait_for_spawn()

    # Authenticating to the lab uses a different part of the client code that
    # also requires redirect loop protection.
    mock_jupyter.set_redirect_loop(enabled=False)
    await client.wait_for_spawn()
    mock_jupyter.set_redirect_loop(enabled=True)
    with pytest.raises(NubladoRedirectError) as exc_info:
        await client.auth_to_lab()

    # Check that the exception contains useful tags for Sentry.
    info = exc_info.value.to_sentry()
    assert info.tags == {
        "httpx_request_method": "GET",
        "httpx_request_url": ANY,
    }

    # The precise point at which we detect the redirect loop depends on
    # whether per-user subdomains are enabled.
    if f"{username}." in str(exc_info.value):
        route = f"/user/{username}/lab"
    else:
        route = f"/user/{username}/oauth_callback"
    assert route in str(exc_info.value)
    assert route in info.tags["httpx_request_url"]


@pytest.mark.asyncio
async def test_execution_failure(client: NubladoClient, username: str) -> None:
    start = datetime.now(tz=UTC)

    await client.auth_to_hub()
    await client.spawn_lab(NubladoImageByClass())
    await client.wait_for_spawn()
    with pytest.raises(NubladoExecutionError) as exc_info:
        async with client.lab_session() as session:
            await session.run_python("1 / 0")

    # Check the properties of the resulting exception.
    exc = exc_info.value
    assert exc.user == username
    assert exc.code == "1 / 0"
    assert f"{username}: running code '1 / 0' failed" in str(exc)
    assert "Error:" in str(exc)
    assert "ZeroDivisionError" in str(exc)
    assert exc.context == CodeContext()
    assert exc.started_at
    assert exc.started_at >= start
    assert exc.failed_at
    assert exc.failed_at >= exc.started_at
    assert exc.status is None

    info = exc.to_sentry()
    assert info.tags == {}
    assert "ZeroDivisionError" in info.attachments["nublado_error.txt"]
    assert info.attachments["nublado_code.txt"] == "1 / 0"
    started_at = format_datetime_for_logging(exc.started_at)
    assert info.contexts["info"]["started_at"] == started_at

    message = exc.to_slack()
    assert message.message == "Error while running code"
    error = message.attachments[-2]
    assert isinstance(error, SlackCodeBlock)
    assert error.heading == "Error"
    assert "ZeroDivisionError" in error.code
    code = message.attachments[-1]
    assert isinstance(code, SlackCodeBlock)
    assert code.heading == "Code executed"
    assert code.code == "1 / 0"

    # Now try again with a context.
    context = CodeContext(
        node="some-node",
        image="some/image:tag",
        notebook="notebook.ipynb",
        cell="some-uuid",
        cell_number="14",
    )
    with pytest.raises(NubladoExecutionError) as exc_info:
        async with client.lab_session() as session:
            await session.run_python("1 / 0", context=context)

    # Check the properties of the resulting exception.
    exc = exc_info.value
    expected = f"{username}: cell some-uuid of notebook notebook.ipynb failed"
    assert expected in str(exc)
    assert "Code: 1 / 0" in str(exc)
    assert "Error:" in str(exc)
    assert "ZeroDivisionError" in str(exc)
    assert exc.context == context

    info = exc.to_sentry()
    assert info.tags == {
        "image": "some/image:tag",
        "node": "some-node",
        "notebook": "notebook.ipynb",
        "cell": "some-uuid",
        "cell_number": "14",
    }
    assert "ZeroDivisionError" in info.attachments["nublado_error.txt"]
    assert info.attachments["nublado_code.txt"] == "1 / 0"

    message = exc.to_slack()
    assert message.message == (
        "Error while running `notebook.ipynb` cell `some-uuid`"
    )
    node = message.blocks[0]
    assert isinstance(node, SlackTextBlock)
    assert node.heading == "Node"
    assert node.text == "some-node"
    cell = message.blocks[1]
    assert isinstance(cell, SlackTextBlock)
    assert cell.heading == "Cell"
    assert cell.text == "`notebook.ipynb` cell `some-uuid` (14)"
    started = message.fields[0]
    assert isinstance(started, SlackTextField)
    assert started.heading == "Started at"
    failed = message.fields[1]
    assert isinstance(failed, SlackTextField)
    assert failed.heading == "Failed at"
    exc_type = message.fields[2]
    assert isinstance(exc_type, SlackTextField)
    assert exc_type.heading == "Exception type"
    assert exc_type.text == "NubladoExecutionError"
    user = message.fields[3]
    assert isinstance(user, SlackTextField)
    assert user.heading == "User"
    assert user.text == username
    image = message.fields[4]
    assert isinstance(image, SlackTextField)
    assert image.heading == "Image"
    assert image.text == "some/image:tag"
