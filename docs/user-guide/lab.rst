.. py:currentmodule:: rubin.nublado.client

################
Using the client
################

A typical interaction with the client usually looks like this:

#. Authenticate to the Hub with `NubladoClient.auth_to_hub` method.
#. Determine whether you already have a running lab with `NubladoClient.is_lab_stopped`.
#. If you need to, spawn a lab with `NubladoClient.spawn_lab`.
#. Wait for the lab to spawn by looping through `NubladoClient.watch_spawn_progress` until you get a progress message indicating the lab is ready.
   Alternately, call `NubladoClient.wait_for_spawn` if you don't care about the spawn messages.
#. Authenticate to the Lab with `NubladoClient.auth_to_lab`.
#. Create a lab session with `NubladoClient.lab_session` (not required when running an entire notebook with `NubladoClient.run_notebook`).
#. Do whatever it is you wanted to do with the lab (see :doc:`lab`).
#. When done, use `NubladoClient.stop_lab` to shut down the lab, if desired.

Running code in JupyterLab
==========================

`NubladoClient` provides three methods of interacting with a spawned lab.
They are:

- `JupyterLabSession.run_python`: Runs a string representing arbitrary Python code and returns standard output from each cell.
  This code will run in the kernel specified by the session (``lsst`` by default).
  This must be done inside a lab session context manager.

- `NubladoClient.run_notebook`: Executes a notebook via the ``/rubin/execution`` endpoint of the  `RSP Jupyter Extensions <https://github.com/lsst-sqre/rsp-jupyter-extensions>`__.
  `Times Square <https://times-square.lsst.io>`__ and `Noteburst <https://noteburst.lsst.io>`__ use this method.
  This API uses `nbconvert <https://nbconvert.readthedocs.io/en/latest/>`__ to execute a notebook and return its rendered form.
  If you need to capture output other than standard output, such as images, use this approach.

Examples
========

Start a lab
-----------

Use the client to determine whether a user lab is running and start it if necessary.
This does not run any code within the lab:

.. code-block:: python

    import asyncio
    from contextlib import aclosing

    import structlog
    from rubin.nublado.client import (
        NubladoClient,
        NubladoImageByClass,
        NubladoImageClass,
        NubladoImageSize,
    )


    async def ensure_lab(client: NubladoClient) -> None:
        await client.auth_to_hub()
        stopped = await client.is_lab_stopped()
        if stopped:
            image = NubladoImageByClass(
                image_class=NubladoImageClass.RECOMMENDED,
                size=NubladoImageSize.Medium,
            )
            await client.spawn_lab(image)
            async with asyncio.timeout(90):
                await client.wait_for_spawn()


    client = NubladoClient(username="some-user", token="some-token")
    asyncio.run(ensure_lab(client))

Execute code inside the lab
---------------------------

Using the above method, run FizzBuzz for ``n`` from 1 to 15:

.. code-block:: python

    import asyncio

    from rubin.nublado.client import NubladoClient

    FIZZBUZZ = """
    output = ""
    for i in range(1, 16):
        if i > 1:
            output += ", "
        if (i % 15 == 0):
            output += "Fizz Buzz\n"
        elif (i % 5 == 0):
            output += "Buzz"
        elif (i % 3 == 0):
            output += "Fizz"
        else:
            output += str(i)
    print(output)
    """


    async def run_fizzbuzz(client: NubladoClient) -> str:
        await ensure_lab(client)
        await client.auth_to_lab()
        async with client.lab_session() as lab_session:
            output = await lab_session.run_python(FIZZBUZZ)
        return output


    client = NubladoClient(username="some-user", token="some-token")
    output = asyncio.run(run_fizzbuzz(client=client))
    print(output)

This will display the following:

.. code-block:: text

   1, 2, Fizz, 4, Buzz, Fizz, 7, 8, Fizz, Buzz, 11, Fizz, 13, 14, Fizz Buzz

Running a notebook
------------------

To execute an entire notebook at once, use `NubladoClient.run_notebook`, which returns a `NotebookExecutionResult` object.
Instead of a list of output strings, this returns the full rendered notebook as a JSON string, along with additional resources used to execute the notebook and the error, if any.
See `NotebookExecutionResult` for the details of the output.

.. code-block:: python

    from pathlib import Path

    from rubin.nublado.client import NubladoClient, NotebookExecutionResult


    async def run_notebook(client: NubladoClient) -> NotebookExecutionResult:
        await ensure_lab(client)
        await client.auth_to_lab()
        notebook_path = Path("path/to/notebook.ipynb")
        return await client.run_notebook(notebook_path.read_text())


    client = NubladoClient(username="some-user", token="some-token")
    result = asyncio.run(run_notebook(client))
    cells = json.loads(result.notebook)["cells"]
    for cell in cells:
        # Do something with each cell
        ...

Error handling
==============

`NubladoClient` may raise a variety of exceptions depending on the problem.
Most anticipated exceptions inherit from `NubladoError`.
`NubladoClient` may also raise `~rubin.repertoire.RepertoireError` or one of its subclasses for failures in service discovery.

`NubladoError` supports Slack reporting and Sentry annotations.
See the Safir documentaiton on `reporting exceptions to Slack <https://safir.lsst.io/user-guide/slack-webhook.html#reporting-an-exception-to-a-slack-webhook>`__ and `integrating with Sentry <https://safir.lsst.io/user-guide/sentry.html>`__ for more information.

Any `NubladoError` or its subclasses can be annotated with a `CodeContext` object to provide additional context about what code was being executed when the exception occurred.
If this information is present, it will be used in Slack and Sentry reporting.
A `CodeContext` model can be assigned to the ``context`` attribute of the exception.
Some `NubladoClient` and `JupyterLabSession` methods take a ``context`` as an optional argument and add it to all raised exceptions.
