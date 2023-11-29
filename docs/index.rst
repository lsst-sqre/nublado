#######
Nublado
#######

Nublado implements a Jupyter notebook service in Kubernetes and a WebDAV file server that provides access to the same underlying POSIX file system.
It is the software that provides the Nobebook Aspect service of the Vera C. Rubin Observatory Science Platform.

This site documents the Nublado service for platform administrators.
Users of the Rubin Science Platform should instead see the documentation at rsp.lsst.io_.

.. _rsp.lsst.io: https://rsp.lsst.io/

Nublado provides only the service to create and manage Kubernetes pods running JupyterLab and the WebDAV file servers.
It can spawn any compatible lab image, although it currently makes assumptions about the versioning scheme that are specific to Rubin Observatory.
For the official Rubin images, see sciplat-lab_.

.. _sciplat-lab: https://github.com/lsst-sqre/sciplat-lab

.. toctree::
   :maxdepth: 2
   :caption: Administration

   about/index
   admin/index
   api

.. toctree::
   :hidden:

   changelog

.. toctree::
   :maxdepth: 2
   :caption: Development

   dev/index
