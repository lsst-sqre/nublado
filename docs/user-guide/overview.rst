.. py:currentmodule:: rubin.nublado.client

#####################
Client usage overview
#####################

The primary class for the Nublado client is `NubladoClient`.
A particular instance of that class represents a single user with an authentication token for a particular RSP environment.
Separate instances of this class must be created for each user and Gafaelfawr_ token used to authenticate to Nublado.

The client talks to JupyterHub and JupyterLab using calls similar to those done by a user's web browser.
It does not talk to the Nublado controller directly.

Obtaining tokens
================

`NubladoClient` must be initialized with a username and a token.
The three most common ways to obtain those are:

- Use a delegated token from a user's request.
  A Gafaelfawr-authenticated ingress that requests a `delegated token <https://gafaelfawr.lsst.io/user-guide/gafaelfawringress.html#requesting-delegated-tokens>`__ will receive the username in the ``X-Auth-Request-User`` request header and the token in the ``X-Auth-Request-Token`` request header.

- Request a service token via a `Kubernetes custom resource <https://gafaelfawr.lsst.io/user-guide/service-tokens.html>`__ and inject that token and the corresponding username into the application.

- Create a new token using the `Gafaelfawr API <https://gafaelfawr.lsst.io/api.html>`__.
  This will require an application token with ``admin:token`` scope and allows specification of the username (in this case, usually a bot user with a username starting with ``bot-``) and scopes.

The application should request ``exec:notebook`` scope, along with any other scopes it may need for any Python code it wants to execute in a notebook.

Sequence of events
==================

A typical interaction with the client usually looks like this:

#. Authenticate to the Hub with `NubladoClient.auth_to_hub` method.
#. Determine whether you already have a running lab with `NubladoClient.is_lab_stopped`.
#. If you need to, spawn a lab with `NubladoClient.spawn_lab`.
#. Wait for the lab to spawn by looping through `NubladoClient.watch_spawn_progress` until you get a progress message indicating the lab is ready.
#. Authenticate to the Lab with `NubladoClient.auth_to_lab`.
#. Create a lab session with `NubladoClient.open_lab_session`.
#. Do whatever it is you wanted to do with the lab (see :doc:`lab`).
#. When done, use `NubladoClient.stop_lab` to shut down the lab, if desired.
