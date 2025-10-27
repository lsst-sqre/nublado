.. _mocks-and-testing:

###################################
Testing users of the Nublado client
###################################

In the module ``rubin.nublado.client`` you will find the ``MockJupyter`` class.
This provides a simulation of the RSP Nublado Hub/Proxy/Controller environment, as well as a partial simulation of the Labs it spawns.
The reason you would use this is to be able to meaningfully test your service without having to test against a live RSP or spin up your own RSP to test the service against.

Creating the mock in a test fixture
===================================

The ``rubin.nublado.client.MockJupyter`` class is fundamentally an instance of the ``respx`` class (used for testing ``httpx`` services), with a websocket emulator patched into it.

It depends on two other fixtures: ``environment_url`` is a string, representing the base URL of the RSP environment, and ``filesystem`` is a ``pathlib.Path`` representing the home directory of the user the ``NubladoClient`` is running as.  These collectively look like:

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
    def test_filesystem() -> Iterator[Path]:
        with TemporaryDirectory() as td:
            # Do whatever you need to do in order to set up the home
            # directory contents here
            yield Path(td)


    @pytest.fixture(ids=["shared", "subdomain"], params=[False, True])
    def jupyter(
        respx_mock: respx.Router,
        environment_url: str,
        test_filesystem: Path,
        request: pytest.FixtureRequest,
    ) -> Iterator[MockJupyter]:
        """Mock out JupyterHub and Jupyter labs."""
        jupyter_mock = mock_jupyter(
            respx_mock,
            base_url=environment_url,
            user_dir=test_filesystem,
            use_subdomains=request.param,
        )

        # respx has no mechanism to mock aconnect_ws, so we have to do it
        # ourselves.
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
            yield jupyter_mock

Note the parameterization of the ``jupyter`` fixture.
This will run all of your application's tests twice, once with the mock configured to simulate running all of Nublado under one hostname and once when simulating user subdomains.
This helps test that your application doesn't make assumptions that are valid in only one of the two possible Nublado configurations.

Once you've done all that, all you will need to do is supply the test fixture ``jupyter`` to your unit tests along with a client to communicate with it.

The client is much simpler.
The only special things you need to do with the ``NubladoClient`` are to configure it with the same environment URL your mock Jupyter has, and give it ``X-Auth-Request-User`` and ``X-Auth-Request-Token`` headers that, in real life, would come in via ``GafaelfawrIngress``.
It will make all its usual HTTP calls, which will be intercepted by the ``jupyter`` test fixture and responded to appropriately.

Mocking payloads
================

The Python code being used as a client payload is expected, in the wild, to run within an RSP kernel; usually the ``LSST`` kernel, which is extremely heavyweight and has a great many features not found in a vanilla Python installation.

The ``MockJupyter`` class contains a pair of methods that enable the user to register code or notebook contents with the mock, and if the mock sees those things as execution payloads, it will reply with the registered results rather than trying to actually execute them.

These methods are ``register_python_result()`` and ``register_extension_result()``.
The first is used for mocking ``run_python()`` and ``run_notebook()``, and the second for mocking ``run_notebook_via_rsp_extension()``.
For any case involving Python that uses modules outside the standard library, use the ``register`` methods to pre-load appropriate replies for that code.

These are generally the only two methods of ``MockJupyter`` that the service developer should use directly.
All tests should then interact with the mock Jupyter service through ``NubladoClient``, possibly with execution output mocked via registration.
