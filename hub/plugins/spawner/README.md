# REST spawner for JupyterHub

Provides an implementation of the JupyterHub `Spawner` class that makes REST API calls to a Nublado lab controller to manage user lab Kubernetes pods.
This is a client of the Nublado controller and an implementation of the [spawner API](https://jupyterhub.readthedocs.io/en/stable/api/spawner.html).

For more details about this architecture, see [SQR-066](https://sqr-066.lsst.io/).
