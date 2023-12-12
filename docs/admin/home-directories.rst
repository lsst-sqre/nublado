##########################
Configure home directories
##########################

By default, Nublado uses :file:`/home/{username}` as the path to the user's home directory.
This home directory is declared as the ``workingDir`` of the user's lab pod, meaning that Kubernetes will set that to the working directory when it starts JupyterLab.

Without configuration, the :file:`/home` path in the container is not configured, and the :file:`/home/{username}` directory will not exist, probably preventing the lab from starting.
You will normally want to mount a file system at the :file:`/home` path in the container or a different path of your choice (see :ref:`home-path`).
See :ref:`config-lab-volumes` for details on mounting volumes in the lab container.

All of this behavior may be customized, as described below.

Choose a home directory strategy
================================

There are three common strategies for how to handle home directories for Nublado lab pods.
One of them is discouraged.
Start by picking which strategy you want to use:

#. Use separate storage solely for home directories for user labs.
   This is the recommended choice for Nublado deployments that do not have interactive UNIX users outside of Nublado, such as cloud-hosted Rubin Science Platform deployments.

#. Configure Nublado to use a subdirectory of the user's regular home directory as their home directory for Nublado labs.
   This allows reuse of existing user home directories that the user also uses for activities outside of Nublado, without intermingling their Nublado configuration files with their regular configuration files.
   This is the recommended choice for on-premises Nublado deployments for users that also have conventional interactive UNIX access.

#. Configure Nublado to use the same home directory as the user uses for non-Nublado activities.
   This choice is possible but *heavily discouraged*.
   JupyterLab assumes that it is the only writer to certain files in the user's home directory, and this approach risks conflicts between the Nublado-managed JupyterLab and labs that the user may run outside of Nublado.
   It has also proven to be awkward and confusing in the common case where users need different configuration files inside Nublado than outside Nublado.

In both of the recommended configurations, you will need to arrange for the user's Nublado home directory to be created.
See :ref:`home-create` for details on how to do that.

.. _home-path:

Configure the home directory path
=================================

The default home directory path of :file:`/home/{username}` is recommended for simplicity if Nublado is the only user of the home directories.
With appropriately chosen volume mounts (see :ref:`config-lab-volumes`), the storage used for user home directories can be mounted as :file:`/home` inside the lab container.

If you are running Nublado in an environment that users also interact with outside of Nublado, you may want to make the path to the user's home directory inside the lab container match what they expect outside of Nublado.
To do this, see the configuration settings documented at :ref:`config-lab-home`.

Ensure Kubernetes can see the home directory
--------------------------------------------

Kubernetes, running as root on a Kubernetes node, must be able to traverse all of the parent directories of the user's home directory.
If you are using NFS as the source of your home directories and the NFS file system is exported with root-squash set (usually the default), the accesses from Kubernetes will show up as the NFS nobody user.
This will mean that all parent directories of the Nublado home directory must be traversable by the nobody user.

This interacts poorly with using a subdirectory of a user's home directory as the Nublado home directory and the typical default home directory permissions of 0700.
With NFS root-squash and that configuration, Kubernetes will fail to determine if the working directory of the container is present, attempt to create it (with the wrong owner), and then most likely fail to do so, preventing the lab from starting.

In this situation, you have three options:

#. Disable root-squash on the NFS server for the Kubernetes cluster where Nublado is running so that Kubernetes can traverse the directory hierarchy as root.
#. Set all parent directories of the Nublado home directory to at least mode 0711 so that any user can traverse (but not read) them.
#. Move the Nublado home directory outside of the user's home directory.

.. _home-create:

Configure user home directory creation
======================================

The home directory for the user must be created before the user's lab container is started.
If it is not, Kubernetes will attempt to create it.
This will either fail, causing the lab to fail to start, or it will succeed, resulting in a home directory owned by root and not writable by the user.
Either way, the user will not be able to use their lab.

Therefore, unless you are already creating the Nublado home directory through some external user provisioning process, you should configure a Nublado init container to create the user home directory on demand.

Nublado provides a container, ``nublado-inithome`` for this purpose.

Configuring nublado-inithome
----------------------------

The following Nublado configuration will tell Nublado to attempt to create the home directory, change its ownership to the user's UID and primary GID, and set its permissions to 0700 before the user's lab container starts:

.. code-block:: yaml

   controller:
     config:
       lab:
         initContainers:
           - name: "inithome"
             image:
               repository: "ghcr.io/lsst-sqre/nublado-inithome"
               tag: "4.0.0"
             privileged: true

The tag should be set to the current released version of Nublado.
You will also need to add a ``volumeMounts`` key to the init container configuration to mount the volume that provides user home directories.
It should match the ``controller.config.lab.volumeMounts`` configuration.

When ``privileged`` is set to true, the init container will run as root (UID 0).
This is usually required to create and set ownership of a new home directory outside of any existing directory owned by the user.
If you are putting the Nublado home directory inside the user's home directory, you can omit the ``privileged: true`` line and let the init container run as the user, who presumably will already have write access to their home directory and can create the subdirectory needed by Nublado.

Common problems
---------------

If the home directory volume is mounted from an NFS server and you are not putting Nublado home directories in an existing user home directory, you must disable root-squash in the NFS mount exported to the Kubernetes cluster where Nublado is running.
If root-squash (usually the default) is set, the init container, running as root, will be mapped to an NFS nobody user, who will not have permissions to create a new user home directory.

If you are using NFS and cannot disable root-squash (due, for example, to local security policies), you may need to arrange for the user's home directory to be created via some mechanism outside of Nublado before the first time the user tries to start a lab.

The ``nublado-inithome`` container can only create a single level of directories.
If you set ``controller.config.lab.homedirSchema`` to ``initialThenUsername``, you will need to precreate the subdirectories for all possible first letters of usernames before ``nublado-inithome`` will be able to create user home directories.

More information
================

See :ref:`config-lab-init` for more information about init containers configuration and :ref:`config-lab-volumes` for more information about mounting volumes in the lab.

If ``nublado-inithome`` does not do what you need, you can run your own init container.
See :doc:`init-containers` for more details.
