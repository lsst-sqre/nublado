##########################
Internal authenticator API
##########################

The module ``rubin.nublado.authenticator`` provides an implementation of the `JupyterHub Authenticator API <https://jupyterhub.readthedocs.io/en/stable/reference/authenticators.html>`__ that uses Gafaelfawr_ to authenticate users.

This authenticator class is registered as ``gafaelfawr`` in the ``jupyterhub.authenticators`` entry point.

.. automodapi:: rubin.nublado.authenticator
   :include-all-objects:
