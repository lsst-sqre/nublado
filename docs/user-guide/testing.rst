.. py:currentmodule:: rubin.nublado.client

###################################
Testing users of the Nublado client
###################################

The `MockJupyter` class can be used to write unit tests of users of the Nublado Python client without needing a running Phalanx environment.
It simulates the subset of the JupyterHub and JupyterLab API used by the Nublado client and simulates Python code execution inside the notebook with `exec`.

.. warning::

   Code for which no result has been registered via
   `MockJupyter.register_python_result` will be executed via `exec`. This
   mock therefore supports arbitrary code execution via its handlers and
   must never be exposed to untrusted messages.

Creating the mock in a test fixture
===================================

`MockJupyter` requires RESPX_ in addition to :py:mod:`rubin.nublado.client`.
Add ``respx`` to your project's development dependencies.

Then, add a fixture (usually to :file:`tests/conftest.py`) that calls `register_mock_jupyter` and yields the `MockJupyter` object.

.. code-block:: python

    from collections.abc import AsyncGenerator

    import pytest
    import respx
    from nublado.rubin.client import MockJupyter, register_mock_jupyter


    @pytest.fixture
    async def mock_jupyter(
        respx_mock: respx.Router,
    ) -> AsyncGenerator[MockJupyter]:
        async with register_mock_jupyter(respx_mock) as mock:
            yield mock

.. warning::

   `register_mock_jupyter` will globally patch the ``websockets.connect`` function to mock the JuypterLab web socket.
   If your application uses ``websockets.connect`` outside of the Nublado client, you cannot use this Jupyter mock and will have to find some other way to test.

`register_mock_jupyter` uses service discovery to determine what Nublado URLs to mock.
You therefore must set up the service discovery mock before setting up the Jupyter mock (such as by declaring it auto-use).
See the `Repertoire documentation <https://repertoire.lsst.io/user-guide/testing.html>`__ for more information.

By default, `register_mock_jupyter` sets up a mock of a Nublado instance configured with per-user subdomains.
If you want to emulate hosting JupyterHub and JupyterLab on the same hostname instead, pass ``use_subdomains=False`` as an argument to `register_mock_jupyter`.
This should be invisible to your application; the Nublado client should transparently handle both configurations.

Writing tests
=============

Any test you write that uses the Nublado client should depend on the ``mock_jupyter`` fixture defined above, directly or indirectly, so that the mock will be in place.
Alternately, you can mark the fixture as `auto-use <https://docs.pytest.org/en/stable/how-to/fixtures.html#autouse-fixtures-fixtures-you-don-t-have-to-request>`__.

When using this mock, you must use a token created with `MockJupyter.create_mock_token` to authenticate.
The result of this static method should be passed in as the ``token`` constructor parameter to `NubladoClient`.
For example:

.. code-block:: python

   from rubin.nublado.client import MockJupyter, NubladoClient


   def test_something(mock_jupyter: MockJupyter) -> None:
       token = mock_jupyter.create_mock_token("some-user")
       client = NubladoClient("some-user", token)

       # More tests go here
       ...

Mocking payloads
----------------

By default, `MockJupyter` runs the code provided to `JupyterLabSession.run_python` using `eval`.
To change this behavior, you can call `MockJupyter.register_python_result`, passing it a code string and a result.
Any subsequent attempt to execute that code string will return the registered result rather than executing the code.

The `MockJupyter.register_notebook_result` method provides similar functionality for `NubladoClient.run_notebook`.
It takes the notebook contents (as a JSON string) and a corresponding `NotebookExecutionResult`.
Any subsequent execution of a notebook matching that string will return the registered notebook execution result.

If `MockJupyter.register_notebook_result` has not been called with a matching notebook string value, the `MockJupyter` replacement for full notebook execution will return the input notebook.
The mock will never attempt to run :command:`nbconvert` in the way that the Nublado JupyterLab extension would do.

Injecting delays
----------------

There are two ways to inject delays into the mock to simulate how long it takes Nublado operations to take on a real cluster:

`MockJupyter.set_delete_delay`
    Wait this long before deleting the lab.
    The lab will be fully delated if at least this long has passed and the client makes a call to the API endpoint listing running labs (called by `NubladoClient.is_lab_stopped`).
`MockJupyter.set_spawn_delay`
    Pause for this long before returning success from the spawn progress route.

Testing Jupyter errors
----------------------

Any Jupyter operation performed by the client can be configured to fail for a given user by calling `MockJupyter.fail_on` and passing in the user and the operation or list of operations that should fail.
The operation should be chosen from `MockJupyterAction`.

There is one other error behavior that can be enabled in the mock:

`~MockJupyter.set_redirect_loop`
    If the parameter ``enabled`` is `True`, tells the mock to return redirect loops from the endpoints for getting the JupyterHub top-level page, the JupyterLab top-level page, and the spawn progress server-sent events API.

Inspecting client behavior
--------------------------

`MockJupyter` provides a few methods that can be used to inspect the internal state of the mock.
This is useful for testing the Nublado client itself, and may be useful when testing software that uses the Nublado client internally to see if it left Jupyter in the expected state.

`~MockJupyter.get_last_spawn_form`
    Returns the contents, as a dictionary, of the last spawn form submitted to the mock.
    Intended primarily to test the client `~NubladoClient.spawn_lab` method.

`~MockJupyter.get_last_notebook_kernel`
    Returns the kernel requested for the last call to `~NubladoClient.run_notebook`, or `None` if the default kernel was used.
    Intended primarily to test the client `~NubladoClient.run_notebook` method.

`~MockJupyter.get_session`
    Returns the current JupyterLab session for a given user, or `None` if there is no current session.
    The session is returned as a `MockJupyterLabSession` object, which contains information about the parameters sent by the client to create the session.
