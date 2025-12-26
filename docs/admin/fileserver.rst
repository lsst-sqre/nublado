################
User fileservers
################

The Nublado controller will, if requested and the functionality is enabled in its configuration, start a fileserver on behalf of a user.
This is a WebDAV server that typically serves the user's home directory.

Phalanx configuration
=====================

The ``fileserver`` service has settings you may wish to modify.
The ones you are most likely to want to change are listed below.

``controller.config.fileserver.enabled``
    A boolean value controlling whether or not the fileserver is enabled.
    The default value is ``false``.

``controller.config.fileserver.idleTimeout``
    How long a user will have had to go without fileserver activity before the fileserver is shut down.
    The default value is one hour.

``controller.config.fileserver.volumeMounts``
    Which volumes are exposed via WebDAV.
    There is no default; this must be specified explicitly.
    Usually, you will want to expose whichever volume includes user home directories.
