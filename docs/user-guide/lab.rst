.. py:currentmodule:: rubin.nublado.client

################
Using the client
################

A typical interaction with the client usually looks like this:

#. Authenticate to the Hub with `NubladoClient.auth_to_hub` method.
#. Determine whether you already have a running lab with `NubladoClient.is_lab_stopped`.
#. If you need to, spawn a lab with `NubladoClient.spawn_lab`.
#. Wait for the lab to spawn by looping through `NubladoClient.watch_spawn_progress` until you get a progress message indicating the lab is ready.
#. Authenticate to the Lab with `NubladoClient.auth_to_lab`.
#. Create a lab session with `NubladoClient.open_lab_session`.
#. Do whatever it is you wanted to do with the lab (see :doc:`lab`).
#. When done, use `NubladoClient.stop_lab` to shut down the lab, if desired.

Running code in JupyterLab
==========================

`NubladoClient` provides three methods of interacting with a spawned lab.
These are methods on the `JupyterLabSession` object you will have available inside the session context manager.
They are:

- `JupyterLabSession.run_python`: Runs a string representing arbitrary Python code and returns standard output from each cell.
  This code will run in the kernel specified by the session (``LSST`` by default).

- `JupyterLabSession.run_notebook`: Runs each cell of a supplied notebook using `JupyterLabSession.run_python`, accumulating the results and returning them as a list of cell outputs.

- `JupyterLabSession.run_notebook_via_rsp_extension`: Executes a notebook via the ``/rubin/execution`` endpoint of the  `RSP Jupyter Extensions <https://github.com/lsst-sqre/rsp-jupyter-extensions>`__.
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
                async with aclosing(client.watch_spawn_progress()) as progress:
                    async for message in progress:
                        if message.ready:
                            break


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
        async with client.open_lab_session() as lab_session:
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

Assume there is a notebook named :file:`notebook.ipynb` in the current directory.
One way to run that notebook is with `JupyterLabSession.run_notebook`, which will run each cell with `JupyterLabSession.run_python`:

.. code-block:: python

    from rubin.nublado.client import NubladoClient


    async def run_notebook(client: NubladoClient) -> list[str]:
        await ensure_lab(client)
        await client.auth_to_lab()
        async with client.open_lab_session() as lab_session:
            return await lab_session.run_notebook(Path("notebook.ipynb"))


    client = NubladoClient(username="some-user", token="some-token")
    output = asyncio.run(run_notebook(client))
    for line in output:
        print(line)

The other way is to use `JupyterLabSession.run_notebook_via_rsp_extension`, which returns a `NotebookExecutionResult` object.
Instead of a list of output strings, this returns the full rendered notebook as a JSON string, along with additional resources used to execute the notebook and the error, if any.

.. code-block:: python

    from rubin.nublado.client import NubladoClient, NotebookExecutionResult


    async def run_notebook(client: NubladoClient) -> NotebookExecutionResult:
        await ensure_lab(client)
        await client.auth_to_lab()
        async with client.open_lab_session() as lab_session:
            return await lab_session.run_notebook_via_rsp_extension(
                Path("notebook.ipynb")
            )


    client = NubladoClient(username="some-user", token="some-token")
    result = asyncio.run(run_notebook(client))
    cells = json.loads(result.notebook)["cells"]
    for cell in cells:
        # Do something with each cell
        ...
