.. _lab-interaction:

########################
Interacting with the lab
########################

``NubladoClient`` provides three methods of interacting with a spawned lab.  These are methods on the ``JupyterLabSession`` object you will have available inside the session context manager.  They are:

#. ``run_python()``.  This runs a string representing arbitrary Python code and returns streamed results (which is to say, ``stdout``, within each cell).  Of course, this code will run in the Lab environment specified by the session, which will be bound to a particular kernel (usually ``LSST`` within the RSP), and will have access to whatever is installed in that kernel.
#. ``run_notebook()``.  This runs each cell of a supplied notebook using ``run_python()``, accumulating the results and ultimately returning them as a list of cell outputs.
#.  ``run_notebook_via_rsp_extension()``.   This executes a notebook via the ``/rubin/execution`` endpoint of the  `RSP Jupyter Extensions <https://github.com/lsst-sqre/rsp-jupyter-extensions>`__.  `Times Square <https://times-square.lsst.io>`__ and `Noteburst <https://noteburst.lsst.io>`__ use this method. The extensions run within the user lab, and the execution extension, in turn, uses `nbconvert <https://nbconvert.readthedocs.io/en/latest/>`__ to execute notebooks and return their rendered form.  If you need to execute a notebook and capture output that did not go to stdout (for instance, the Javascript created by a Bokeh call, that will ultimately run in your browser), this is at present the way to do it.

.. _client-use-examples:

Usage examples
==============

The following uses the client to determine whether a user Lab is
running and to start it if necessary.  It does not run any code within
the Lab:

.. code-block:: python

    """Ensure there's a running lab for the user."""

    import asyncio
    from contextlib import aclosing

    import structlog

    from rubin.nublado.client import (
        GafaelfawrUser,
        NubladoClient,
        NubladoImageByClass,
        NubladoImageClass,
        NubladoImageSize,
    )

    LAB_SPAWN_TIMEOUT = 90


    async def ensure_lab() -> None:
        """Start a Lab if one is not present."""
        client = NubladoClient(
            user=GafaelfawrUser(username="some-user", token="some-token"),
            base_url="https://data.example.org",
        )
        await client.auth_to_hub()
        stopped = await client.is_lab_stopped()
        if stopped:
            image = NubladoImageByClass(
                image_class=NubladoImageClass.RECOMMENDED,
                size=NubladoImageSize.Medium,
            )
            await client.spawn_lab(image)
            progress = client.watch_spawn_progress()
            async with aclosing(progress):
                async with asyncio.timeout(LAB_SPAWN_TIMEOUT):
                    async for message in progress:
                        if message.ready:
                            break


    asyncio.run(ensure_lab())

The next example assumes that you have already done the above--that is, you know the user already has a running Lab--and that you, for some reason, want to run FizzBuzz for n=1 through 100:

.. code-block:: python

    """Run Fizzbuzz in the RSP"""

    import asyncio

    from rubin.nublado.client import GafaelfawrUser, NubladoClient

    client = NubladoClient(
        user=GafaelfawrUser(username="some-user", token="some-token"),
        base_url="https://data.example.org",
    )
    FIZZBUZZ = """
    i=1
    accum=""
    while (i<=100):
        if i>1:
            accum += ", "
        if (i%15 == 0):
            accum += "Fizz Buzz"
        elif (i%5 == 0):
            accum += "Buzz"
        elif (i%3 == 0):
            accum += "Fizz"
        else:
            accum += str(i)
        i += 1
    print(accum)
    """


    async def run_fizzbuzz(client: NubladoClient) -> str:
        await client.auth_to_hub()
        await client.auth_to_lab()
        async with client.open_lab_session() as lab_session:
            output = await lab_session.run_python(FIZZBUZZ)
        return output


    output = asyncio.run(run_fizzbuzz(client=client))
    print(output)

This will display the following:

.. code-block:: text

    1, 2, Fizz, 4, Buzz, Fizz, 7, 8, Fizz, Buzz, 11, Fizz, 13, 14, Fizz Buzz, 16, 17, Fizz, 19, Buzz, Fizz, 22, 23, Fizz, Buzz, 26, Fizz, 28, 29, Fizz Buzz, 31, 32, Fizz, 34, Buzz, Fizz, 37, 38, Fizz, Buzz, 41, Fizz, 43, 44, Fizz Buzz, 46, 47, Fizz, 49, Buzz, Fizz, 52, 53, Fizz, Buzz, 56, Fizz, 58, 59, Fizz Buzz, 61, 62, Fizz, 64, Buzz, Fizz, 67, 68, Fizz, Buzz, 71, Fizz, 73, 74, Fizz Buzz, 76, 77, Fizz, 79, Buzz, Fizz, 82, 83, Fizz, Buzz, 86, Fizz, 88, 89, Fizz Buzz, 91, 92, Fizz, 94, Buzz, Fizz, 97, 98, Fizz, Buzz

For the next two examples, we will assume that you have a notebook called ``HelloGoodbye.ipynb`` in your home directory.  This notebook contains two cells.  The first cell's code is:

.. code-block:: python

    print("Hello, world!")

and the second cell's code is:

.. code-block:: python

    print("Goodbye, world!")

Then the following will run the notebook via each method, compare their outputs, and if they are the same, print the outputs with the line number followed by a colon and a space before each one:

.. code-block:: python

    import asyncio
    import json

    from dataclasses import dataclass
    from pathlib import Path

    from rubin.nublado.client import (
        GafaelfawrUser,
        NubladoClient,
        NotebookExecutionResult,
    )


    @dataclass
    class NBResults:
        session_output: list[str]
        extension_output: NotebookExecutionResult


    client = NubladoClient(
        user=User(username="some-user", token="some-token"),
        base_url="https://data.example.org",
    )
    notebook = Path("HelloGoodbye.ipynb")


    async def run_notebook_both_ways(
        client: NubladoClient, notebook: Path
    ) -> NBResults:
        await client.auth_to_hub()
        await client.auth_to_lab()
        async with client.open_lab_session() as lab_session:
            session_output = await lab_session.run_notebook(notebook)
            extension_output = await lab_session.run_notebook_via_rsp_extension(
                path=notebook
            )
        return NBResults(
            session_output=session_output, extension_output=extension_output
        )


    output = asyncio.run(run_notebook_both_ways(client=client, notebook=notebook))
    obj = json.loads(output.extension_output.notebook)
    cells = obj["cells"]
    # Check that the output is the same from both methods.  We have to do a
    # lot of work to pull the streaming output out of the cell.
    outputs_from_extension: list[str] = []
    for cell in cells:
        if (
            "cell_type" in cell
            and cell["cell_type"] == "code"
            and "outputs" in cell
            and cell["outputs"]
        ):
            cell_outputs = cell["outputs"]
            for outp in cell_outputs:
                if (
                    "output_type" in outp
                    and outp["output_type"] == "stream"
                    and "name" in outp
                    and outp["name"] == "stdout"
                    and "text" in outp
                    and outp["text"]
                ):
                    text_list = outp["text"]
                    for text in text_list:
                        if text:
                            outputs_from_extension.append(text)

    if outputs_from_extension == output.session_output:
        for count, line in enumerate(output.session_output):
            print(f"{count+1}: {line.strip()}")

This yields:

.. code-block:: text

    1: Hello, World!
    2: Goodbye, World!
