.. py:currentmodule:: rubin.nublado.client

###################################
Testing users of the Nublado client
###################################

The `MockJupyter` class can be used to write unit tests of users of the Nublado Python client without needing a running Phalanx environment.
It simulates the subset of the JupyterHub and JupyterLab API used by the Nublado client and simulates Python code execution inside the notebook with `eval`.

Creating the mock in a test fixture
===================================

`MockJupyter` requires RESPX_ in addition to :py:mod:`rubin.nublado.client`.
Add ``respx`` to your project's development dependencies.

Then, add a fixture (usually to :file:`tests/conftest.py`) to create the `MockJupyter` class and patch the underlying WebSocket connection used for the JupyterLab kernel.

.. code-block:: python

    from collections.abc import AsyncGenerator, Iterator
    from contextlib import asynccontextmanager
    from pathlib import Path
    from unittest.mock import patch

    import pytest
    import respx
    import websockets

    from nublado.rubin.client import (
        MockJupyter,
        MockJupyterWebSocket,
        mock_jupyter,
        mock_jupyter_websocket,
    )


    @pytest.fixture
    def environment_url() -> str:
        return "https://data.example.org"


    @pytest.fixture
    def user_dir() -> Path:
        return Path(__file__).parent / "data" / "files"


    def jupyter(
        respx_mock: respx.Router, environment_url: str, user_dir: Path
    ) -> Iterator[MockJupyter]:
        mock = mock_jupyter(respx_mock, environment_url, user_dir)

        @asynccontextmanager
        async def mock_connect(
            url: str,
            extra_headers: dict[str, str],
            max_size: int | None,
            open_timeout: int,
        ) -> AsyncGenerator[MockJupyterWebSocket, None]:
            yield mock_jupyter_websocket(url, extra_headers, jupyter_mock)

        with patch.object(websockets, "connect") as mock:
            mock.side_effect = mock_connect
            yield mock

Note the separate ``environment_url`` and ``user_dir`` fixtures.
These can be customized as desired.
For example, you may change the ``user_dir`` path to where you keep test notebooks for your service.

By default, `MockJupyter` emulates a Nublado instance running in a single domain.
If you want to emulate per-user subdomains instead, pass ``use_subdomains=True`` as an argument to `mock_jupyter`.
This should be invisible to your application; the Nublado client should transparently handle both configurations.

Writing tests
=============

Any test you write that uses the Nublado client should depend on the ``jupyter`` fixture, directly or indirectly, so that the mock will be in place.

When creating a token used by `NubladoClient` for your tests, ensure the token has the format :samp:`gt-{username}.{random}` where the username portion is the base64-encoded username passed as a constructor argument to `NubladoClient`.
The random portion can be anything.
This special token format is required by `MockJupyter`; requests where the token is missing or does not match the username will be rejected, usually resulting in test failures.

Here is a function that generates suitable tokens:

.. code-block:: python

   import os
   from base64 import urlsafe_b64encode


   def create_token(username: str) -> str:
       encoded_username = urlsafe_b64encode(username.encode()).decode()
       return f"gt-{encoded_username}.{os.urandom(4).hex()}"

Mocking payloads
----------------

By default, `MockJupyter` runs the code provided to `JupyterLabSession.run_python` or `JupyterLabSession.run_notebook` using `eval`.
To change this behavior, you can call `MockJupyter.register_python_result`, passing it a code string and a result.
Any subsequent attempt to execute that code string will return the registered result rather than executing the code.

The `MockJupyter.register_extension_result` method provides similar functionality for `JupyterLabSession.run_notebook_via_rsp_extension`.
It takes the notebook contents (as a JSON string) and a corresponding `NotebookExecutionResult`.
Any subsequent execution of a notebook matching that string will return the registered notebook execution result.

If `MockJupyter.register_extension_result` has not been called with a matching notebook string value, the `MockJupyter` replacement for full notebook execution will return the input notebook.
The mock will never attempt to run :command:`nbconvert` in the way that the Nublado JupyterLab extension would do.
