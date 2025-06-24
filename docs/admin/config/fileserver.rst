##############################
User file server configuration
##############################

A user file server is a WebDAV server created on demand for a specific user to provide remote access to POSIX file systems.
The intent is to provide the same paths that are available inside the user's lab via WebDAV, which allows users to mount the file system on their local machine and more easily copy files back and forth from their lab environment.

Enable file servers
===================

File servers are disabled by default and must be explicitly enabled.

``controller.config.fileserver.enabled``
    Set to true to allow users to create file servers.
    The default is false.

Mounted volumes
===============

``controller.config.fileserver.volumeMounts``
    A list of volumes to expose to the user over WebDAV.
    The volumes must correspond to volumes specified in ``controller.config.lab.volumes``.
    The syntax of each entry is identical to the syntax of ``controller.config.lab.volumeMounts`` (see :ref:`config-lab-volumes`).

    None of the volumes mounted in the main lab container are mounted in user file servers by default.
    To expose those mounts via WebDAV, they must be listed explicitly here.
    The ``containerPath`` setting is the relative path at which the volume will appear in WebDAV.

    These mounts are independent of the main container mounts and thus can have different paths, sub-paths, and so forth, and can reference volumes not mounted in the main container.

Image
=====

The following settings configure which Docker image to use as a WebDAV file server.
The Nublado controller uses a specific set of environment variables to configure the WebDAV file server that are only supported by worblehat_, so the only reason to change these settings is when testing a new unreleased version.

``controller.config.fileserver.image.repository``
    Docker repository from which to get the WebDAV file server image.
    The default is the Docker repository for worblehat_.

``controller.config.fileserver.image.pullPolicy``
    Pull policy for the file server image.
    The default is ``IfNotPresent``.
    Change to ``Always`` if you are iterating on new file server versions with the same tag, such as a Jira ticket branch.

``controller.config.fileserver.image.tag``
    Tag for the file server image.
    The default is the latest stable release.

Kubernetes
==========

``controller.config.fileserver.application``
    Name of the Argo CD application with which to tag user file server resources.
    This tagging causes all of the user file server resources to show up in Argo CD, which has been convenient for deleting broken file servers or viewing pod logs.
    The default is ``nublado-fileservers`` and should not normally be changed, since Phalanx sets up an application by that name for this purpose.

``controller.config.fileserver.namespace``
    Kubernetes namespace in which to create user file servers.
    The default is ``fileservers`` and should not normally be changed, since Phalanx sets up a namespace for this purpose.
    If file servers are enabled, this namespace must exist when the Nublado controller starts; it will not create it.

``controller.config.fileserver.resources``
    Resource limits and requests for user file server pods.
    The defaults are chosen based on observed metrics from Google Kubernetes Engine.

``controller.config.fileserver.reconcileInterval``
    How frequently to reconcile file server state with Kubernetes.
    This will detect when file servers or their supporting Kubernetes resources disappear unexpectedly, such as by manual deletions.
    This can be safely set to a long interval since normal file server pod terminations should be caught by a separate Kubernetes watch.
    The default is one hour.

None of the following are set by default.
They can be used to add additional Kubernetes configuration to all lab pods if, for example, you want them to run on specific nodes or tag them with annotations that have some external meaning for your environment.

``controller.config.fileserver.affinity``
    Affinity rules for user file server pods.

``controller.config.fileserver.extraAnnotations``
    Extra annotations to add to all file server pods.

``controller.config.fileserver.nodeSelector``
    Node selector rules for user file server pods.

``controller.config.fileserver.tolerations``
    Toleration rules for user file server pods.

Timeouts
========

``controller.config.fileserver.creationTimeout``
    How long in seconds to wait for Kubernetes to start the file server.
    The default is 120 (two minutes).

``controller.config.fileserver.deleteTimeout``
    How long in seconds to wait for Kubernetes to delete a file server.
    The default is 60 (one minute).

``controller.config.fileserver.idleTimeout``
    After this length of time in seconds, the file server exits and is automatically cleaned up to save cluster resources.
    If the user needs to use the file server again, they will need to restart it by going to the ``/files`` URL (or other URL set by ``controller.config.fileserver.pathPrefix``).
    The default is 3600 (one hour).

Path prefix
===========

``controller.config.fileserver.pathPrefix``
    The path prefix to use for the user file server routes.
    The default is ``/files``.
    You probably do not want to change this unless you are trying to run multiple instances of Nublado in the same Phalanx environment for some reason.
