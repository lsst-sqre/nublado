.. _client-usage:

#####################
Client usage overview
#####################

The ``NubladoClient`` is designed to make interaction with JupyterHub and Jupyterlab, as they are configured in the RSP environment, easy.

A particular instance of the client represents a single user in a particular RSP environment.
A user, in this context, means a token (which will have a set of scopes allowing various actions within the RSP) bound to a username.
Both of these will be available in the service you are writing with each request, in the ``X-Auth-Request-Token`` and ``X-Auth-Request-User`` headers on the request.
You should not, in general, need to go to Gafaelfawr to extract any further information about the token, but you must be prepared to handle 401s and 403s in case the token you have is invalid, expired, or does not grant sufficient scope for the service you want to use.

Sequence of events
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
