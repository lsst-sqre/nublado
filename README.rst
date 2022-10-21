######################################
jupyterlab-controller (aka Nublado v3)
######################################

Controller for creation of JupyterLab resources in the RSP.

The third attempt at our Notebook Aspect controller is defined in
`sqr-066<https://sqr-066.lsst.io>`_.  This is an implementation of that
design, or more
precisely
`a lightly modified sqr-066<https://sqr-066.lsst.io/v/DM-36570/index.html>`_.

Organization
============

The `source for the
controller<https://github.com/lsst-sqre/jupyterlab-controller/tree/tickets/DM-36570>`_
is organized basically like
`Gafaelfawr<https://github.com/lsst-sqre/gafaelfawr>`_.  Inside the
`source directory<../src/jupyterlabcontroller>`_, you will find the
standard `models` and `handlers` directories.

Business logic will be
mostly found in ``services``, and ``docker`` and ``kubernetes`` contain
the pieces that communicate directly with each of those backend
endpoints.

The ``dependencies`` directory turns the Kubernetes
CoreV1API client into a FastAPI dependency; we do not do a similar thing
with the Docker client because it relies on the already-built-in httpx
dependency.

Finally, the ``runtime`` directory contains runtime convenience
functions and utilities.

Lab Controller Configuration
============================

`configuration.yaml<./configuration.yaml>`_ is what will eventually go
into the `Phalanx<https://github.com/lsst-sqre/phalanx>`_
`services/nublado` `values.yaml` as the `controller` section of
configuration.  That work is being tracked in
`a branch<https://github.com/lsst-sqre/phalanx/tree/tickets/DM-36570>`_.

This will be mounted into the controller pod as
``/etc/nublado/configuration.yaml`` and will be accessible inside the
application as ``controller_config``, as well as its three components
addressable as ``lab_config``, ``prepuller_config``, and ``form_config``
dictionaries.  These are loaded at runtime by
`config.py<../src/jupyterlabcontroller/runtime/config.py>`_.




jupyterlab-controller is developed with the `Safir <https://safir.lsst.io>`__ framework.
`Get started with development with the tutorial <https://safir.lsst.io/set-up-from-template.html>`__.
