###################
User Migration Tool
###################

A common issue in RSP instances is that a user has lost access to their old institutional account, failed to set up access through an account such as GitHub that they did get to keep, created a new account, and then want their original files back.

While we can certainly accomodate those users via doing a manual copy with fsadmin, it is less than ideal, especially as the volume of such user requests grows.
Thus we have created a REST API that allows migration of old users to new users.

This is conceptually similar to the ``fsadmin`` service, in that it creates a privileged pod and performs file operations as root-equivalent.
It differs from that service in that it presents a very limited API: in essence, the only thing it allows is "copy old user A's file into a subdirectory of user B's space".

Note that in particular this interface does no removal of the old user's files.
That must be done manually via the ``fsadmin`` interface at the moment.
This is a conscious design choice to limit the risk from this interface.

This service must have its own scope.
It is an admin scope, although it is much more limited than full administrative access.

User Migration API
==================

#. ``GET`` to ``/nublado/migrator/v1/service`` with ``old_user`` and ``new_user`` query parameters returns ``200`` if a migration of ``old_user`` to ``new_user`` is currently in progress.
It returns ``204`` if no such operation is in progress.
The HTTP body for a a response is JSON with three fields:
   #. ``start_time``, whose value is a textual representation of a UTC ISO 8601 datestamp showing the time the pod was created.
   #. ``end_time``, whose value is a textual representation of a UTC ISO 8601 datestamp showing the time the pod exited (or ``null`` if it has not exited).
   #. ``exit_code``, whose value is the exit code of the migrator pod process (or ``null`` if the pod has not exited).

In any case that does not return a ``200`` indicating an operation in progress, the completed pod, if any, will be removed.
Thus the querier gets only one chance to read the pod's exit status, which is encoded in the ``exit_code`` field of the JSON response.

#. ``POST`` to ``/nublado/migrator/v1/service`` with ``old_user`` and ``new_user`` parameters set in the JSON message body, where each is a username, initiates the file copy, assuming that both ``old_user`` and ``new_user`` have home directories.

Visible Effects
===============

The contents of the old user's home space will be copied into the new user's home space, at ``migrated-<old-user>-<timestamp>``.
All files there will be owned by the new user.
Group ownership will be set to the new user's primary group.
Symlink targets will not be touched, so if users have absolute symlinks to items within their home directories, they will have to update those by hand.
