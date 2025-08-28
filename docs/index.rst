#######
Nublado
#######

Nublado implements a Jupyter notebook service in Kubernetes, a WebDAV file server that provides access to the same underlying POSIX file system, a mechanism for starting and stopping a pod that can connect to the POSIX file system with administrative privileges, and a client for speaking to the Jupyter notebook service and the Labs it spawns, along with a set of mocks to be used when developing a service with that client.
It is the software that provides the Nobebook Aspect service of the Vera C. Rubin Observatory Science Platform.

This site documents the Nublado service for platform administrators.
Users of the Rubin Science Platform should instead see the documentation at rsp.lsst.io_.

.. _rsp.lsst.io: https://rsp.lsst.io/

Nublado provides only the service to create and manage Kubernetes pods running JupyterLab, the WebDAV file servers, and a client for talking to the Jupyter service and the Labs it spawns (as well as a set of mocks for users of the client to use).
Nublado's Jupyter Service can spawn any compatible lab image, although it currently makes assumptions about the versioning scheme that are specific to Rubin Observatory.
For the official Rubin images, see sciplat-lab_.

.. _sciplat-lab: https://github.com/lsst-sqre/sciplat-lab

.. toctree::
   :maxdepth: 2

   about/index

.. toctree::
   :maxdepth: 2

   admin/index

.. toctree::
   :maxdepth: 2

   client/index

.. toctree::

   api

.. toctree::
   :hidden:

   changelog

.. toctree::
   :maxdepth: 2

   dev/index
