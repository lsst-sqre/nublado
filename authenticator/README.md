# Gafaelfawr JupyterHub authenticator

This is an implementation of the JupyterHub `Authenticator` class that authenticates a user using [Gafaelfawr](https://gafaelfawr.lsst.io), assuming authentication is configured using [Phalanx](https://phalanx.lsst.io).
It is, in theory, generic, and is maintained as a stand-alone Python module, but is normally installed in a Docker image with JupyterHub as part of the Rubin Science Platform JupyterHub build.

For more details about this architecture, see [SQR-066](https://sqr-066.lsst.io/).
