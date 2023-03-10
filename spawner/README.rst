###############
rsp-restspawner
###############

This is a JupyterHub Spawner class to allow spawning JupyterLab pods for
users via the jupyterlab-controller (aka nublado v3).

It implements the spawner API described at
https://jupyterhub.readthedocs.io/en/stable/api/spawner.html .

In ``rsp-restspawner`` the spawner API is implemented with a simple REST
client that operates against the service described in
https://sqr-066.lsst.io.
