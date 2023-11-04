# RSP JupyterHub build

This directory holds the build machinery for the modified JupyterHub build used by the Notebook Aspect of the Rubin Science Platform.

The RSP JupyterHub is a combination of the standard JupyterHub build plus a custom authenticator and a custom spawner.
The authenticator and spawner are maintained as separate Python library packages with normal floating dependencies.
However, for a reproducible JupyterHub image build, we want to pin all Python dependencies and add some supplemental scripts.

This directory contains the pinned Python dependencies and the supplemental scripts.
It is used by `Dockerfile.hub` when building the JupyterHub image.
The pinned dependencies here are only used for that image, and may differ from the pinned dependencies for the Nublado controller.
