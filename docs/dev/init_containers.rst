###########################################
Interface to initContainers from controller
###########################################

The controller will launch initContainers prior to spawning the user's lab if ``config.lab.initContainers`` is not empty.

The first, and currently only, use case for initContainers in the Nublado context is to allow for automated provisioning of home directories.
This presumes that the underlying Kubernetes infrastructure has sufficient privileges to write as root (or equivalent) to the user filesystem structures, and to change ownership and file permissions on the filesystem objects it creates.

Each container in this list will be run in turn.
In addition to whatever static configuration is present in the config snippet, the controller is responsible for injecting per-container information into the initContainers.
This is done by setting environment variables in the containers.

Environment Variables in initContainers
---------------------------------------

The controller sets ``NUBLADO_UID``, ``NUBLADO_GID``, and ``NUBLADO_HOME`` as environment variables inside each initContainer it starts.

* ``NUBLADO_UID`` contains the UID of the user for whom the Lab is being created.
* ``NUBLADO_GID`` contains the GID of the user's primary group.
* ``NUBLADO_HOME`` contains the path to the user's home directory.

