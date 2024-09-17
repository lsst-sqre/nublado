############
Client guide
############

This page describes the use of the ``NubladoClient`` class and especially its provided testing classes.

.. _client-usage:

Using the Client
================

The ``NubladoClient`` is designed to make interaction with JuptyerHub and Jupyterlab, as they are configured in the RSP environment, easy.

A particular instance of the client represents a single user in a particular RSP environment.
A user, in this context, means a token (which will have a set of scopes allowing various actions within the RSP) bound to a username.
Both of these will be available in the service you are writing with each request, in the ``X-Auth-Request-Token`` and ``X-Auth-Request-User`` headers on the request.
You should not, in general, need to go to Gafaelfawr to extract any further information about the token, but you must be prepared to handle 401s and 403s in case the token you have is invalid, expired, or does not grant sufficient scope for the service you want to use.

Sequence of Events
==================

A typical interaction with the client usually looks like this:

#. Authenticate to the Hub with the ``auth_to_hub()`` method.
#. Determine whether or not you have a running lab with ``is_lab_stopped()``.
#. If you need to, spawn a lab with ``spawn_lab()``.
#. Wait for the lab to spawn by looping through ``watch_spawn_progress()`` until you get a progress message indicating the lab is ready.
#. Authenticate to the Lab with ``auth_to_lab()``
#. Use ``open_lab_session()`` as a context manager to interact with your lab.
#. Do whatever it is you wanted to do with the lab; more below.
#. When done, use ``stop_lab()`` to shut down the lab, if desired.

The ``client_test`` test in the client test suite steps through this process and may be a useful model.

.. _lab-interaction:

Interacting With The Lab
========================

``NubladoClient`` provides three methods of interacting with a spawned lab.  These are methods on the ``JupyterLabSession`` object you will have available inside the session context manager.  They are:

#. ``run_python()``.  This runs a string representing arbitrary Python code and returns streamed results (which is to say, ``stdout`` wihin each cell).  Of course, this code will run in the Lab environment specified by the session, which will be bound to a particuar kernel (usually ``LSST`` within the RSP), and will have access to whatever is installed in that kernel.
#. ``run_notebook()``.  This runs each cell of a supplied notebook using ``run_python()``, accumulating the results and ultimately returning them as a list of cell outputs.
#.  ``run_notebook_via_rsp_extension()``.  As is obvious from the name, this is not a standard Jupyter feature.  This runs a notebook in the same way ``Times-Square`` does, by using a Rubin Observatory-specific extension within the user lab that, in turn, uses ``nbconvert`` to execute notebooks and return their rendered form.  If you need to execute a notebook and capture output that did not go to stdout (for instance, the Javascript created by a Bokeh call, that will ultimately run in your browser), this is at present the way to do it.

.. _Mocks:

Mocks
=====

In the module ``rubin.nublado.client.testing`` you will find the ``MockJupyter`` class.
This provides a simulation of the RSP Nublado Hub/Proxy/Controller environment, as well as a partial simulation of the Labs it spawns.
The reason you would use this is to be able to meaningfully test your service without having to test against a live RSP or spin up your own RSP to test the service against.
Although there are quite a few additional classes within the module, ``MockJupyter`` should be the only one you need directly.
In the client test suite, there is a context manager ``jupyter`` which is an illustration of how to create a MockJupyter (which is fundamentally based on the ``respx`` class for testing ``httpx`` services) and monkeypatch in a websocket emulator.
Once you have a mocked Jupyter in play, you should not need to do very much else: use a regular ``NubladoClient``, and if you have configured it and the mock for the same base URL, the mock should respond appropriately.

Mocking Payloads
----------------

The attentive reader will have noticed a potential problem.
The Python code being used as a client payload is expected, in the wild, to run within an RSP kernel.
The ``LSST`` kernel is extremely heavyweight and has all kinds of features not found in a vanilla Python installation.
How can we unit-test this without installing the DM stack in our test suite?

Fortunately, the ``MockJupyter`` class contains a pair of methods that enable the user to register code or notebook contents with the mock, and if the mock sees those things as execution payloads, it will reply with the registered results rather than trying to actually execute them.

These methods are ``register_python_result()`` and ``register_extension_result()``.
The first is used for mocking ``run_python()`` and ``run_notebook()``, and the second for mocking ``run_notebook_via_rsp_extension()``.
These are generally the only two methods of ``MockJupyter`` that the service developer should use directly.
All other interaction with it will be via the handlers it uses as it mocks routes with ``respx``, which is to say: use the ``NubladoClient`` and let it make HTTP and websocket calls that are intercepted by the ``MockJupyter`` and handled appropriately.
For any case involving Python that uses modules outside the standard library, use the ``register`` methods to pre-load appropriate replies for that code.

.. _examples:

Examples
========

The `Ghostwriter <https://ghostwriter.lsst.io/v>`_ service uses ``NubladoClient``.  Soon `Mobu <https://mobu.lsst.io>`_ and `Noteburst <https://noteburst.lsst.io>`_ will as well.
