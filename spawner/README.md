# rsp-restspawner

Provides an implementation of the JupyterHub `Spawner` class that makes REST API calls to a Nublado lab controller to manage user lab Kubernetes pods.
This is a client of [https://github.com/lsst-sqre/jupyterlab-controller/](jupterlab-controller) and an implementation of the [spawner API](https://jupyterhub.readthedocs.io/en/stable/api/spawner.html).

Currently, this repository also provides an implementation of the JupyterHub `Authenticator` class that authenticates a user using [Gafaelfawr](https://gafaelfawr.lsst.io/), assuming authentication is configured using [Phalanx](https://phalanx.lsst.io/).
It also builds the Docker image that is used as JupyterHub in a Rubin Science Platform installation.
In the future, these components will be broken into separate repositories or separate directories in a monorepo.

For more details about this architecture, see [SQR-066](https://sqr-066.lsst.io/).
