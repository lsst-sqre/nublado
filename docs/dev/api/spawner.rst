####################
Internal spawner API
####################

The module ``rubin.nublado.spawner`` provides an implementation of the `JupyterHub Spawner API <https://jupyterhub.readthedocs.io/en/stable/reference/spawners.html>`__ that uses the Nublado controller to manage user labs.

This authenticator class is registered as ``nublado`` in the ``jupyterhub.spawners`` entry point.

.. automodapi:: rubin.nublado.spawner
   :include-all-objects:
