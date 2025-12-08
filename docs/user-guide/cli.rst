Command-line interface
======================

.. click:: nublado.cli:main
   :prog: nublado
   :nested: full

Controller
----------

The Nublado controller doesn't have a command-line interface.
It should be started via ``uvicorn``, using ``nublado.controller.main:create_app`` as the entry point, with host ``0.0.0.0`` and port ``8080``.

Filesystem Administration
-------------------------

The filesystem administration function is simply to start the container with root privilege and then keep the container alive while allowing ``kubectl exec`` access to the pod.
Typically it will be started with an innocuous command such as ``tail -f /dev/null``.

Repository Cloning
------------------

The repository cloner is not started through the ``nublado`` command-line interface.
Instead, the shell entrypoint will be invoked directly as ``/usr/local/bin/repo-cloner.sh`` (typically from a Kubernetes CronJob).

