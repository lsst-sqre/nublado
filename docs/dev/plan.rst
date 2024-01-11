########################
Nublado development plan
########################

This page documents known work required, planned, or proposed for Nublado as an aid to resource and timeline planning.

Before end of construction
==========================

Security fixes
--------------

- All file servers must be covered by a ``NetworkPolicy``.
  Ideally, we would do egress blocking, but I'm not sure if that works with NFS volume mounts, so we'll need to test.
  But at the least ingress should be restricted to the ingress-nginx pod similar to what we do with all other Gafaelfawr-protected services.

Architectural changes
---------------------

- Remove the ``Service`` resource created for the user's lab and instead follow kubespawner in returning a lab URL that points directly to the pod.
  This will hopefully fix the spurious error messages we see during lab shutdown, since it allows the proxy to continue to talk to the pod even once it's been put in terminating state.
  (The ``Service`` immediately drops pods in terminating state.)

- Merge the WebDAV file server into the Nublado monorepo.

- Send progress percentage on completion events as well, and update the REST Spawner to accept that.

- Move user state information into Redis instead of memory and support running multiple Nublado controllers.
  This allows restarting without a service outage and avoids various race conditions with JupyterHub restarts.
  Move the watches into a separate controller service that only has to watch Kubernetes state and update Redis, since it will need to be a singleton (or otherwise do some sort of work partitioning to avoid duplicate updates).

- Determine how to scale JupyterHub to multiple pods.

API changes
-----------

- Listing all users should show every user for whom we're willing to return status, not just those with running labs.

Configuration
-------------

- Verify that all volumes are used by either the lab or an init container and every volume references by the lab or init container exists.

- Support a simple way to add additional users and groups to the NSS files in the container, such as a list of additional users or additional groups with their data elements.
  Currently, one has to override the entire file template just to add an extra group for better ``ls`` output.

- Make the mount paths for various automatic volume mounts configurable.

- Diagnose conflicts between built-in volume mounts and configured volume mounts (such as ``/opt/lsst/software/jupyterlab/runtime``).

- Make all timeouts configurable instead of hard-coded.

- Provide a configuration option saying to run the inithome container so that we can automatically use the same version number as the Nublado controller and not require people bump the version number for each Nublado release.

Known bugs
----------

- kubernetes-asyncio can apparently raise ``aiohttp.client_exceptions.ClientOSError`` for connection reset by peer, and we don't catch this or handle it appropriately.
  The right fix for this may be in kubernetes-asyncio, or we may not be catching a wide enough range of exceptions in the Kubernetes storage layer.

- Reduce the slightly excessive Kubernetes permissions the Nublado controller has for ``Ingress`` resources.
  See if we can also restrict its permissions on ``Secret`` resources.

- Move secrets from JupyterHub out of the environment and into the lab secret, and do not report them as part of the API.

- Don't blindly follow ``WWW-Authenticate`` data when authenticating to Docker hubs.
  Instead, only allow a specific list of remote authentication endpoints.
  Currently, we would potentially leak authentication credentials if someone could tamper with the ``WWW-Authenticate`` reply.

- httpx timeouts don't seem to be honored with server-sent event streams.

New features
------------

- Extract severity of namespace events from the Kubernetes object and pass it via the progress protocol to the REST spawner.

- Add timestamps to the progress messages.

- Parse ``WWW-Authenticate`` returned by Gafaelfawr to get better Gafaelfawr errors.

Code cleanup
------------

- Add test helper functions to manipulate pods (particularly pod status) and namespace events in test cases to reduce code duplication.

- Fix internal object naming conventions to be consistent with other services.

- Replace the arbitrary delays in the test suite with condition variables or Kubernetes mock watches.

Documentation
-------------

- Move the huge comment in the fileserver handlers into a development section of the manual or somewhere else where it will show up in the development documentation.

- Update :sqr:`066` to reflect changes during implementation and to remove the API information that should now be generated directly from the Nublado controller itself.

Minor changes
-------------

- Change the file server namespace and Argo CD app to ``nublado-fileservers`` instead of ``fileservers`` for parallelism (and sorting) with ``nublado-users``.

- Use standard Kubernetes labels for the file servers where possible instead of custom Nublado labels.

- Get rid of the unused singleuser ``NetworkPolicy`` installed by Zero to JupyterHub.

- Reject users without a GID rather than falling back on using the UID as the GID.

- Reconsider the labels and annotations that are added to created pods.

- Change lab extensions to use ``JUPYTER_IMAGE_SPEC`` instead of ``JUPYTER_IMAGE`` and retire the latter.

Operations
----------

- Move the session database to infrastructure PostgreSQL.
  The in-cluster PostgreSQL server should only be used for minikube and test deployments.

- Use standard containers for the in-cluster PostgreSQL server rather than an old, unpatched custom container.
  This will require mounting startup scripts and configuration into a third-party container or finding a good third-party Helm chart (or both).

- Get the upstream Zero to JupyterHub ``NetworkPolicy`` working so that we can stop maintaining our own.

Future work
===========

Architectural changes
---------------------

- Implement retries for Kubernetes calls, similar to what Kubespawner did, to make the controller more robust against temporary control plane problems.

- Monitor lab status with a long-running watch so that labs can simply exit to indicate that the user wants to shut them down.
  Use this to back out of adding our own menu options that make ``DELETE`` calls to JupyterHub, which in turn lets us delegate fewer permissions to the lab.
  The lab can instead simply exit and the exit will be noticed by the watch by the lab controller, which can then send the ``DELETE`` to JupyterHub to clean up state.
  Note that this assumes it's okay to hold open watches equal to the number of running labs.
  We will need to validate this performance assumption to ensure it doesn't overload the Kubernetes control plane.

- Add identifiers to spawn progress events and add resumption support to the REST spawner.

- Convert to the new Kubernetes Events API instead of using core events.

New features
------------

- Add JupyterHub administrator permissions for members of ``g_admins`` so that we can use the JupyterHub UI and API.

- Move Docker client code out of the Nublado controller and build an image pruner using the same basic code.

Minor changes
-------------

- Convince the semver package to use ``__all__`` at the top level so that mypy recognizes what symbols are exported and we don't have to import symbols from submodules.
