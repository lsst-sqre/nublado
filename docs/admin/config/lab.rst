######################
User lab configuration
######################

The settings under ``controller.config.lab`` configure the user's lab environment.
That configuration includes volumes and volume mounts, environment variables, secrets, injected files, and user and group information, as well as Kubernetes configuration such as timeouts and a pull secret.

.. _config-lab-home:

Home directory paths
====================

By default, Nublado uses :file:`/home/{username}` as the home directory path for each user.
If you want to use a different home directory path, normally to match a home directory layout used by non-Nublado services in the same environment, set one or more of the following configuration options:

``controller.config.lab.homedirPrefix``
    The portion of the home directory path before the username.
    The default value is ``/home``.
    The primary reason to set this to something else is to match a home directory path used by users of the same environment outside of Nublado.

``controller.config.lab.homedirSchema``
    How to construct the username portion of the home directory path.
    This must be set to one of the following values:

    ``username``
        Append only the username, resulting in a path like :file:`/home/{username}`.
        This is the default.

    ``initialThenUsername``
        Append the first character of the username, a slash, and then the username, resulting in a path like :file:`/home/{u}/{username}`.

``controller.config.lab.homedirSuffix``
    The portion of the home directory path to add after the username.
    This is most commonly used to locate the Nublado home directory in a subdirectory of the home directory the user uses outside of Nublado.
    For example, setting this to ``rsphome`` will result in a path like :file:`/home/{username}/rsphome`.
    The default is the empty string (do not append any additional path).

These configuration settings only control the home directory path *inside the lab container*.
You will need to arrange for the appropriate volume to be mounted into the container so that these paths are valid.
For information about how to do that, see :ref:`config-lab-volumes`.

For a comprehensive guide to deciding how to handle home directories in Nublado, see :doc:`/admin/home-directories`.

.. _config-lab-volumes:

Mounted volumes
===============

By default, labs only have node-local temporary space (a Kubernetes ``emptyDir``) mounted in :file:`/tmp` and some read-only metadata mounted.
All other mounted file systems must be explicitly specified, including the user's home directory if you want users to have persistent home directories.

As with Kubernetes in general, the volumes and volume mounts are specified separately.
This allows the list of volumes to be shared with init containers (see :ref:`config-lab-init`) and for the same volume to be mounted multiple times.

``controller.config.lab.volumes``
    List of volumes available for mounting in the main lab container (via ``controller.config.lab.volumeMounts``), init containers (via the ``volumeMounts`` key of an init container), or file servers (via ``controller.config.fileserver.volumeMounts``).
    Each volume must have the following settings:

    ``name``
        Name of the volume.
        This is used as-is in the Kubernetes spec and therefore must be a valid Kubernetes name.
        It must also be unique among all of the volumes.

    ``source``
        Source specification for the volume.
        The type of source volume is determined by ``source.type``.
        Each type of source volume requires different settings.
        See :ref:`config-lab-volume-host`, :ref:`config-lab-volume-nfs`, and :ref:`config-lab-volume-pvc`.

``controller.config.lab.volumeMounts``
    List of volume mounts for the main lab container.
    Each volume mount has the following settings:

    ``containerPath``
        Where to mount this volume inside the container.
        For example, ``/home``.

    ``volumeName``
        The name of the volume (from ``controller.config.lab.volumes``) to mount.

    ``subPath``
        Subdirectory of the source volume to mount.
        By default, if this is not specified, the top of the source volume is mounted.

    ``readOnly``
        If set to true, the volume is mounted read-only.
        The default is false.

Nublado currently supports three types of volumes, each specified with the ``source`` key of an entry in ``controller.config.lab.volumes``.

.. _config-lab-volume-host:

Host path volumes
-----------------

A host path volume mounts a file system that is already mounted on the Kubernetes node hosting the pod.
It is usually used for distributed file systems on non-cloud Kubernetes clusters.

Host path volumes have the following settings in their ``source`` key:

``type``
    Must be set to ``hostPath``.

``path``
    The path on the Kubernetes node to mount into the container.
    This is the path on the host node, not the path *inside* the container.
    The path inside the container is set by ``containerPath`` in the volume mount configuration.

.. _config-lab-volume-nfs:

NFS volumes
-----------

A volume mounted from an NFS server.
NFS volumes have the following settings in their ``source`` key:

``type``
    Must be set to ``nfs``.

``server``
    The host name or IP address of the NFS server.

``serverPath``
    The exported path of the volume on the NFS server.

``readOnly``
    Whether to mount the volume read-only at the NFS protocol layer.
    This is a lower-level setting than the ``readOnly`` setting on the volume mount.
    Unlike the volume mount setting, it tells the NFS client that the volume is mounted read-only and all writes will be prevented even if the volume mount specifies read/write.

.. _config-lab-volume-pvc:

PVC volumes
-----------

A volume mounted from a Kubernetes ``PersistentVolumeClaim``.
This can use any storage mechanism available to Kubernetes ``PersistentVolume`` resources in the Kubernetes cluster.
A corresponding ``PersistentVolumeClaim`` will be created for each user lab inside the user's lab namespace.

PVC volumes have the following settings in their ``source`` key.

``type``
    Must be set to ``persistentVolumeClaim``.

``accessModes``
    A list of Kubernetes access modes.
    Because the same volumes are mounted for every user's lab pod, only the access modes ending in ``Many`` are supported, namely ``ReadOnlyMany`` and ``ReadWriteMany``.

``storageClassName``
    Name of the storage class.

``resources``
    Resource requests for the volume in the normal Kubernetes syntax for persistent volume claims.

``readOnly``
    If set to true, forces all mounts of this volume to be read-only.
    This is a lower-level setting than the ``readOnly`` setting on the volume mount and effectively overrides it, although the error message for attempted writes may be different.

Environment variables
=====================

``controller.config.lab.env``
    Additional environment variables for all user labs.
    The value must be key and value pairs to add to the environment.
    These settings will be public in the GitHub Phalanx repository, so do not use this mechanism for secrets.
    You can also override specific default environment variables set in :file:`values.yaml` for the Phalanx ``nublado`` application by setting that key to a different value, although do this with caution.

You can also set environment variables from secrets.
See :ref:`config-lab-secrets` for how to do that.

Files
=====

``controller.config.lab.files``
    Static files to inject into every user lab.
    This setting should consist of key and value pairs.
    The key is the path to the file inside the lab, and the value is the contents that file should have.

    These settings will be public in the GitHub Phalanx repository, so do not use this mechanism for secrets.
    Instead, see :ref:`config-lab-secrets`.

``controller.config.lab.nss.baseGroup``
    The base contents of :file:`/etc/group` inside the container.
    This is used to show group names instead of GIDs in, for example, :command:`ls` listings.
    To this, the Nublado controller will add entries for all of the user's primary and supplemental groups.
    The default is suitable for the base sciplat-lab_ image.

    It is normally not necessary to override this setting.
    The one time when that may be useful is to add additional GID to group mappings for groups the user is not a member of, so that they can be resolved to human-readable names.
    However, be cautious of creating duplicates of the records added by the Nublado controller, with possibly unpredictable results.

    When overriding this setting, be sure to include any necessary entries from the default setting.

``controller.config.lab.nss.basePasswd``
    The base contents of :file:`/etc/passwd` inside the container.
    This is used to show user names instead of UIDs in, for example, :command:`ls` listings.
    To this, the Nublado controller will add an entry for the user who is spawning the lab.
    The default is suitable for the base sciplat-lab_ image.

    It is normally not necessary to override this setting.
    The one time when that may be useful is to add additional UID to username mappings so that they can be resolved to human-readable names.

    When overriding this setting, be sure to include any necessary entries from the default setting.

.. _config-lab-secrets:

Lab Secrets
===========

The Nublado controller can create a Kubernetes ``Secret`` resource alongside the uesr lab and use that to pass secrets to the lab.

``controller.config.lab.secrets``
    A list of secret definitions.
    Each secret is a string value that can be injected as either environment variables or mounted files.
    The same secret value is injected for every lab, so do not use this for per-user secrets.
    The default is an empty list (no injected secrets).

    All secrets will be visible as files under the path :file:`/opt/lsst/software/jupyterlab/secrets`.
    The name of the file is the key of the secret (``secretKey`` below) and the contents of the file are the value of the secret.
    Secrets can also be injected as environment variables or files mounted elsewhere, as described below.

    Each secret definition may have the following settings:

    ``secretName``
        Name of the Kubernetes ``Secret`` in the same namespace as the Nublado controller from which to read the secret.
        Normally this must be ``nublado-lab-secret``, which is created by Phalanx from the configured Nublado secrets.

    ``secretKey``
        The key within that secret whose value should be injected into the lab.
        This key name must be unique across all defined lab secrets.

    ``env``
        Environment variable inside the lab to set to the value of this secret.
        The default is to not set an environment variable.

    ``path``
        File to create inside the lab with contents equal to the value of this secret.
        The default is to not create an additional file containing this secret.

.. _config-lab-init:

Init containers
===============

Nublado supports running additional containers during the startup of the lab pod as Kubernetes init containers (see `the Kubernetes documentation <https://kubernetes.io/docs/concepts/workloads/pods/init-containers/>`__ for more details).
These containers may be privileged, unlike the lab containers which always run as the user who spawned the lab.

Examples of why one may want to run an init container include creating the user's home directory if it doesn't already exist or doing networking setup for the lab container that requires privileged operations.

Configure init containers with the following setting:

``controller.config.lab.initContainers``
    A list of init containers to run before the main lab container is started.
    Each init container has the following settings:

    ``name``
        Name of the init container.
        This is copied into the Kubernetes manifest as the Kubernetes name for the init container, so must be a valid Kubernetes name and must be unique across all init containers.

    ``image.repository``
        Repository of the image to run.
        For example, ``docker.io/lsstit/ddsnet4u``.

    ``image.pullPolicy``
        Kubernetes pull policy of the image.
        The default is ``IfNotPresent``.
        Set to ``Always`` when testing an init container by repeatedly pushing new container images with the same tag.

    ``image.tag``
        Tag of the init container to run.
        For example, ``1.4.2``.

    ``privileged``
        If set to true, the container is run as a privileged container with all capabilities and as the root user.
        The default is false, which runs the container as the lab user with the same restrictions and permissions as the main lab container.

    ``volumeMounts``
        A list of volumes to mount inside the container.
        The volumes must correspond to volumes specified in ``controller.config.lab.volumes``.
        The syntax of each entry is identical to the syntax of ``controller.config.lab.volumeMounts`` (see :ref:`config-lab-volumes`).
        None of the volumes mounted in the main lab container are mounted in init containers by default, so if the init container needs access to them, those mounts must be reiterated here.
        They are independent of the main container mounts and thus can have different paths, sub-paths, and so forth, and can reference volumes not mounted in the main container.

For more details on init containers and how to write your own, see :doc:`/admin/init-containers`.
For a guide to the specific use case of setting up user home directories, see :doc:`/admin/home-directories`.

Lab sizes
=========

When the user requests a new lab, they are asked to choose from a menu of possible lab sizes.
These sizes correspond to Kubernetes resource limits and requests for the created pod.
See the `Kubernetes documentation <https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/>`__ for more details.

``controller.config.lab.sizes``
    The list of available lab sizes from which the user can choose.
    If the user has a notebook quota set (see `quota settings in Gafaelfawr <https://gafaelfawr.lsst.io/user-guide/helm.html#quotas>`__), only sizes that fit within that quota will be shown.
    The order in which the sizes are listed will be preserved in the menu, and the first size listed will be the default.

    The default setting defines three sizes: ``small`` with 1 CPU unit and 4GiB of memory, ``medium`` with 2 CPU units and 8GiB of memory, and ``large`` with 4 CPU units and 16GiB of memory.

    Each element of the list must contain the following keys:

    ``size``
        The human-readable name of this lab size.
        Must be chosen from ``fine``, ``diminutive``, ``tiny``, ``small``, ``medium``, ``large``, ``huge``, ``gargantuan``, and ``colossal`` (taken from `d20 creature sizes`_).

    ``cpu``
        Number of CPU units to set as a limit.
        If the pod attempts to use more CPU processing than this limit, it will be throttled.

    ``memory``
        Memory allocation limit.
        If the pod attempts to allocate more memory than this limit, processes will be killed by the Linux OOM killer.
        In practice, this often means the pod will become unusable and will have to be recreated.

    The ``cpu`` and ``memory`` for a given lab size define the Kubernetes limits.
    The Kubernetes requests are automatically set to 25% of the limits.

.. _config-lab-kubernetes:

Kubernetes
==========

``controller.config.lab.application``
    Name of the Argo CD application with which to tag user lab resources.
    This tagging causes all of the user lab resources to show up in Argo CD, which has been convenient for deleting broken labs or viewing pod logs.
    The default is ``nublado-users`` and should not normally be changed, since Phalanx sets up an application by that name for this purpose.

``controller.config.lab.namespacePrefix``
    Prefix used in constructing the names of user lab namespaces.
    All lab resources for a user will be put into a Kubernetes namespace whose name is formed by appending ``-`` and the username to the value of this setting.
    The default is ``nublado``.

``controller.config.lab.pullSecret``
    The name of a pull secret to use for lab images.
    This is only needed if Docker is used as an image source (see :ref:`config-images-source`) and if credentials are required to talk to the Docker registry.
    This may be required to access private image registries, or to lift the restrictive rate limit Docker Hub imposes on unauthenticated clients.
    If set, it should be set to the string ``pull-secret``, which will be created by Phalanx.
    The default is unset.

    See `the Phalanx documentation <https://phalanx.lsst.io/admin/update-pull-secret.html>`__ for more details about managing a pull secret in Phalanx.

``controller.config.lab.reconcileInterval``
    How frequently to reconcile lab state with Kubernetes.
    This will detect when user labs disappear without user action, such as when they are terminated by Kubernetes node replacement or upgrades.
    The default is five minutes.

None of the following are set by default.
They can be used to add additional Kubernetes configuration to all lab pods if, for example, you want them to run on specific nodes or tag them with annotations that have some external meaning for your environment.

``controller.config.lab.affinity``
    Affinity rules for user lab pods.

``controller.config.lab.extraAnnotations``
    Extra annotations to add to all user lab pods.

``controller.config.lab.nodeSelector``
    Node selector rules for user lab pods.
    This also restricts which nodes images are prepulled to.

``controller.config.lab.tolerations``
    Toleration rules for user lab pods.
    These tolerations are also applied to when choosing which nodes to prepull images to.

Timeouts
========

``controller.config.lab.deleteTimeout``
    How long to wait for Kubernetes to delete a user's lab in seconds, before failing the deletion with an error.
    The default is one minute.
    If the deletion fails and the user is left with a partially-deleted lab, the deletion will be retried when the user tries to spawn a new lab.

``controller.config.lab.spawnTimeout``
    How long to wait for Kubernetes to spawn the lab in seconds, before failing the lab creation with an error.
    This only counts the time until Kubernetes believes the pod is running and does not include the time required for the lab process itself to start responding to network requests.
    This timeout must be long enough to include the time required to pull the image for images that are not prepulled.
    The default is ten minutes.

JupyterHub has a separate timeout that you may need to adjust:

``hub.timeout.startup``
    How long in seconds to wait for the user's lab to start responding to network connections after the pod has started.
    Empirically, sciplat-lab_ images sometimes take over 60 seconds to start.
    The default is 90 seconds.
