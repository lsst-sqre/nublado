#######################
Running init containers
#######################

Nublado supports running init containers before the user's main lab container to perform any necessary setup before the lab container starts.
The most common use of these init containers is to set up the user's home directory (see :doc:`home-directories`), but they can be used for other purposes.

Write an init container
=======================

Nublado can run any containers of your choice as init containers.

Only the default entry point will be run.
There is no way to override the default entry point with a custom command.

By default, the init container is run with the same UID, primary GID, and supplemental groups as the user, and with privilege escalation disabled.
However, the init container may be marked as privileged, in which case it is run as root (UID 0) as a trusted container with full capabilities.

Environment variables
---------------------

The following environment variables will be set when the init container is invoked:

``NUBLADO_HOME``
    The path to the user's home directory inside the lab container.
    Note that this may not be the path inside the init container if the ``volumeMounts`` configuration for the init container do not match the lab container.
    This will take into account all the settings in :ref:`config-lab-home`.

``NUBLADO_UID``
    The numeric UID of the user whose lab is being created.

``NUBLADO_GID``
    The numeric primary GID of the user whose lab is being created.

Configure an init container
===========================

See :ref:`config-lab-init` for the details of configuring Nublado init containers.
See :doc:`home-directories` for more information about the specific use case of setting up user home directories, and the init container that Nublado provides for that purpose.

Here is an example of an init container configuration for a purpose other than setting up home directories: the init container that is used at "science" sites to set up the appropriate CST landing page and ensure that Markdown opens in the viewer rather than the editor by default.

.. code-block:: yaml

   controller:
     config:
       lab:
         initContainers:
           - name: "cst-landing"
             image:
               repository: "us-central1-docker.pkg.dev/rubin-shared-services-71ec/\
sciplat/cst-landing"
          volumeMounts:
            - containerPath: "/home"
              volumeName: "home"
            - containerPath: "/rubin"
              volumeName "rubin"

