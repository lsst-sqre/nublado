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

Any test you write that uses the Nublado client should depend on the ``mock_jupyter`` fixture, directly or indirectly, so that the mock will be in place.

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

By default, `MockJupyter` runs the code provided to `JupyterLabSession.run_python` using `eval`.
To change this behavior, you can call `MockJupyter.register_python_result`, passing it a code string and a result.
Any subsequent attempt to execute that code string will return the registered result rather than executing the code.

The `MockJupyter.register_extension_result` method provides similar functionality for `NubladoClient.run_notebook`.
It takes the notebook contents (as a JSON string) and a corresponding `NotebookExecutionResult`.
Any subsequent execution of a notebook matching that string will return the registered notebook execution result.

If `MockJupyter.register_extension_result` has not been called with a matching notebook string value, the `MockJupyter` replacement for full notebook execution will return the input notebook.
The mock will never attempt to run :command:`nbconvert` in the way that the Nublado JupyterLab extension would do.
