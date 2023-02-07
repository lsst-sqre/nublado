######################################
jupyterlab-controller (aka Nublado v3)
######################################

This is a controller for management of Notebook Aspect resources in the
RSP.

The third attempt at our Notebook Aspect controller is defined in
`sqr-066 <https://sqr-066.lsst.io>`__.  This is an implementation of
that design, or more precisely `a lightly modified sqr-066
<https://sqr-066.lsst.io/v/DM-36570/index.html>`__.

There are three fundamental functions, interrelated but distinct, that
the controller provides:

* Lab resource control
* Prepulling of desired images to nodes
* Construction of the options form supplied to the user by JupyterHub

Source Organization
===================

The `source for the controller
<https://github.com/lsst-sqre/jupyterlab-controller/tree/tickets/DM-36570>`__
is organized basically like `Gafaelfawr
<https://github.com/lsst-sqre/gafaelfawr>`__.  Inside the `source
directory <../src/jupyterlabcontroller>`__, you will find the standard
`models` and `handlers` directories.

Business logic will be mostly found in ``services``, and ``docker`` and
``kubernetes`` contain the pieces that communicate directly with each of
those backend endpoints.

The ``dependencies`` directory turns the Kubernetes CoreV1API client
into a FastAPI dependency; we do not do a similar thing with the Docker
client because it relies on the already-built-in httpx dependency.

Finally, the ``runtime`` directory contains runtime convenience
functions and utilities.

Controller Configuration
========================

`configuration.yaml <./configuration.yaml>`__ is what will eventually go
into the `Phalanx <https://github.com/lsst-sqre/phalanx>`__
`services/nublado` `values.yaml` as the `controller` section of
configuration.  That work is being tracked in `a branch
<https://github.com/lsst-sqre/phalanx/tree/tickets/DM-36570>`__.

This will be mounted into the controller pod as
``/etc/nublado/configuration.yaml`` and will be accessible inside the
application as ``controller_config``, as well as its three components
addressable as ``lab_config``, ``prepuller_config``, and ``form_config``
dictionaries.  These are loaded at runtime by `config.py
<../src/jupyterlabcontroller/runtime/config.py>`__.

The jupyterlab-controller application is developed with the `Safir
<https://safir.lsst.io>`__ framework.  `Get started with development
with the tutorial <https://safir.lsst.io/set-up-from-template.html>`__.
