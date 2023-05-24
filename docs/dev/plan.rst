########################
Nublado development plan
########################

This page documents known work required, planned, or proposed for Nublado as an aid to resource and timeline planning.

Before data.lsst.cloud deployment
=================================

Documentation
-------------

- Update session clearing documentation in Phalanx to use the JupyterHub pod.

- Review the operational documentation for ``nublado2`` and move anything still relevant to the documentation for the new Nublado application.

Operations
----------

- Run tutorial notebooks on data-dev and data-int for better testing of new Nublado releases.
  This requires a fix to one notebook that asserts that it only runs in the data.lsst.cloud environment.

Rollout
-------

- Write the Phalanx configuration for Nublado v3 for data.lsst.cloud and USDF production.

- Add the required secrets, including 1Password configuration, for Nublado v3 on data.lsst.cloud and USDF production.

- Switch data.lsst.cloud and USDF production to Nublado v3.

Before end of 2023
==================

Architectural changes
---------------------

- Decide whether to migrate to a single repository.
  If not, rename the repositories to more appropriate names.
  If so, merge or at least consider merging all of the relevant repositories into a single repository structure.
  This includes at least the Nublado controller, the REST spawner, the authenticator class, the build process for our custom JupyterHub image, the helper library for labs, the build process for lab images, the file server code, the in-cluster PostgreSQL images (until we can replace them), and the init container used for Google environments.
  Consider how we'll do releases going forward, since Git tags are repository-wide and therefore the most natural way (but not the only way) to do releases from a monorepo is to release all components together and use a unified version number for Nublado as an overall service.

- Move the task watching for namespace events during pod spawn into the user state structure so that it can be managed by the state manager directly, rather than cascading the two background tasks and having the spawn task manage the event watch task.

- Complete the migration of Kubernetes object construction into the builder class.
  Consider separate builder classes for labs, prepull pod, and file servers.
  Collect all name generation for objects into the builders.
  Use this to simplify the API to the Kubernetes storage layer: rather than a separate function to create or read each underlying Kubernetes object, create or retrieve all Kubernetes objects of interest for a lab, file server, or prepull pod in a single call with a domain model.
  This reduces code duplication by allowing one exception handler for the entire method, as long as we use a variable holding the current object being acted on that is updated before each Kubernetes API call and is used in the exception handler to report which specific object caused problems.

- The new Kubernetes watch layer looks like it could benefit from being reworked using inheritance so that it can expose a narrow API for specific operations on types of objects while still sharing code internally.
  Move it to a separate storage layer from the rest of the Kubernetes storage object, since it's conceptually a separate operation.
  Fix the typing, which right now makes very heavy use of ``Any`` (which should be possible to do in a more object-oriented structure).
  This will also eliminate the need for a method map.

- Merge user state management across labs and file servers so that there is one object per known user with all of the state and any running background tasks related to that user.
  This will allow all users to share the same task management and reaper code.
  Making the user state object persistent even if they don't currently have a running lab will also reduce the risk of race conditions.
  The locking around multiple file server creation for a user should then move into the same structure.

- Separate volumes from volume mounts, following Kubernetes, and give volumes names.
  This will allow the same volume to be mounted multiple times and will clear up the problem where init containers appear to specify volumes but have to share them with the lab.
  Verify that all volumes are used by either the lab or an init container and every volume references by the lab or init container exists.
  Name PVCs after the human-chosen volume name (probably with a prefix) instead of autogenerating names.

API changes
-----------

- Add more structure to the lab status rather than flattening pod status and lab specification into one object.

Known bugs
----------

- Find and fix the mock or test code that is erroneously introducing snake-case keys into the raw object of our watches.

- Fix or hide the broken default exit menu option that doesn't work because it redirects to a URL without a leading ``http:`` or ``https:``.

- kubernetes-asyncio can apparently raise ``aiohttp.client_exceptions.ClientOSError`` for connection reset by peer, and we don't catch this or handle it appropriately.
  The right fix for this may be in kubernetes-asyncio, or we may not be catching a wide enough range of exceptions in the Kubernetes storage layer.

- All file servers should be covered by a ``NetworkPolicy``.
  Ideally, we would do egress blocking, but I'm not sure if that works with NFS volume mounts, so we'll need to test.
  But at the least ingress should be restricted to the ingress-nginx pod similar to what we do with all other Gafaelfawr-protected services.

- Reduce the slightly excessive Kubernetes permissions the Nublado controller has for ``Ingress`` resources.

- Remove resource requests for file servers and only have limits.
  If we're short on resources, we want to starve file servers, and we probably do not want to trigger cluster scale-up solely to provide minimum resources to a file server.

- The error message for deleting a nonexistent file server should be a normal 404.

- Report prepull timeouts to Slack.

- Move secrets from JupyterHub out of the environment and into the lab secret, and do not report them as part of the API.

- Don't blindly follow ``WWW-Authenticate`` data when authenticating to Docker hubs.
  Instead, only allow a specific list of remote authentication endpoints.
  Currently, we would potentially leak authentication credentials if someone could tamper with the ``WWW-Authenticate`` reply.

- Test scale-up and see if there is still a bug where spawning the lab suddenly stops with no obvious error message if the cluster had to scale up to spawn it.

- Reconsider the current lab sizes.
  We constantly trigger scale-up for CPU long before we exhaust available memory, which probably implies the balance between CPU and memory is wrong.

- Cap offered lab sizes to the user's quota.

New features
------------

- Extract severity of namespace events from the Kubernetes object and pass it via the progress protocol to the REST spawner.

- Add timestamps to the progress messages.

- Add support for pod tolerations and affinities for lab and file server pods.

Code cleanup
------------

- PR to kubernetes-asyncio to fall back on type annotations when return type information is not available in the docstring when decoding objects in a watch.
  This will allow us to use the ``object`` key instead of having to fall back on the ``raw_object`` key.

- Switch all the tests over to the new utility functions for reading test data instead of using fixtures, which saves some cognitive complexity.

- Add test helper functions to manipulate pods (particularly pod status) and namespace events in test cases to reduce code duplication.

- Delete the unused template for ``GafaelfawrIngress``.

- Fix the file server tests to not require separate fixtures.
  We should be able to use the same fixtures for the file server tests except for a test that routes return the right errors if no file server is configured.

- Rename file server tests to use standard test naming conventions.

- Fix internal object naming conventions to be consistent with other services.

- Push titlecasing of lab sizes down into the form generation code, rather than exposting other parts of the code to it.

- Move checking the user against the username in the path into a dependency to avoid repeating that code.

- Move the multi-reader, multi-writer event stream implementation that is currently copied in the controller, the REST spawner, and the Kubernetes mock in Safir, into its own data type in Safir, and modify all the users to use that instead.

Documentation
-------------

- Write a manual.

- Generate API documentation using reDoc and embed that in the manual.

- Generate internal Python API documentation as part of the manual to aid development.

- Move the huge comment in the fileserver handlers into a development section of the manual or somewhere else where it will show up in the development documentation.

- Maintain a change log using scriv.

- Adopt a release process using the change log, similar to Safir, Gafaelfawr, mobu, etc.

- Update :sqr:`066` to reflect changes during implementation and to remove the API information that should now be generated directly from the Nublado controller itself.

Minor changes
-------------

- Change the file server namespace and Argo CD app to ``nublado-fileservers`` instead of ``fileservers`` for parallelism (and sorting) with ``nublado-users``.

- Use standard Kubernetes labels for the file servers where possible instead of custom Nublado labels.

- Get rid of the unused singleuser ``NetworkPolicy`` installed by Zero to JupyterHub.

- Stop mounting ``/tmp`` in the controller pod, since it shouldn't be needed.

- Pin the single-user server package as well as JupyterHub to suppress the warnings about version mismatches (even though it's not clear that package is being used in our configuration).

- Reject users without a GID rather than falling back on using the UID as the GID.

- Run init containers as the user by default.

Rollout
-------

- Write the Phalanx configuration for Nublado v3 for Telescope and Site deployments.

- Add the required secrets, including 1Password configuration, for Nublado v3 for Telescope and Site deployments.

- Switch to Nublado v3 on Telescope and Site deployments.

Before end of construction
==========================

Architectural changes
---------------------

- Monitor lab status with a long-running watch so that labs can simply exit to indicate that the user wants to shut them down.
  Use this to back out of adding our own menu options that make ``DELETE`` calls to JupyterHub, which in turn lets us delegate fewer permissions to the lab.
  The lab can instead simply exit and the exit will be noticed by the watch by the lab controller, which can then send the ``DELETE`` to JupyterHub to clean up state.
  Note that this assumes it's okay to hold open watches equal to the number of running labs.
  We will need to validate this performance assumption to ensure it doesn't overload the Kubernetes control plane.

- Send progress percentage on completion events as well, and update the REST Spawner to accept that.

- Move user state information into Redis instead of memory and support running multiple Nublado controllers.
  This allows restarting without a service outage and avoids various race conditions with JupyterHub restarts.
  Move the watches into a separate controller service that only has to watch Kubernetes state and update Redis, since it will need to be a singleton (or otherwise do some sort of work partitioning to avoid duplicate updates).

- Determine how to scale JupyterHub to multiple pods.

- Add identifiers to spawn progress events and add resumption support to the REST spawner.

- Convert to the new Kubernetes Events API instead of using core events.

API changes
-----------

- Listing all users should show every user for whom we're willing to return status, not just those with running labs.

Configuration
-------------

- Replace the ``rw`` and ``ro`` enum in volume configuration with a ``readOnly`` boolean flag.
  This has the same range of values but is more self-documenting and matches how Kubernetes thinks about volume mounts.

- Separate NSS configuration from other arbitrary files mounted into the container.
  These do not work like any other files and are always created, so instead of using the ``modify: true`` marker, make their configuration entirely separate.
  We don't have a use case for templating arbitrary files currently, and if we do in the future I am dubious that it should look like the way we assemble NSS files.

- Move NSS file templates out of :file:`values.yaml`.
  This sort of template is better expressed as a simple file on disk, and we can use Helm functions to load the value from disk if we pay a small price in making the ``ConfigMap`` construction a bit more complex.
  This also future-proofs handling of potential new container OSes that may want different default users.
  We would not want to handle that by overriding the whole file, which would be long and ugly; this allows us to instead use ``values.yaml`` to choose from a set of alternative base files.

- Support a simple way to add additional users and groups to the NSS files in the container, such as a list of additional users or additional groups with their data elements.
  Currently, one has to override the entire file template just to add an extra group for better ``ls`` output.

- Diagnose conflicts between built-in volume mounts and configured volume mounts (such as ``/tmp``).

- Move the configuration under the ``safir`` key to the top level.
  "Safir" is not a meaningful type of configuration to an administrator of Nublado and shouldn't be exposed in the configuration language.

- Move ``dockerSecretsPath`` into the lab image configuration, since that is the only component that uses it.

- Configure the prepuller namespace separately from the prefix for user lab namespaces, since these are conceptually unrelated.

- Stop using ``BaseSettings`` and environment variable configuration, since we always inject a configuration file instead.
  This will eliminate warnings from Pydantic.

- Move the Argo CD application names into Helm configuration instead of hard-coding them in the source code.

- Make all timeouts configurable instead of hard-coded.

Known bugs
----------

- httpx timeouts don't seem to be honored with server-sent event streams.

New features
------------

- Parse ``WWW-Authenticate`` returned by Gafaelfawr to get better Gafaelfawr errors.

Code cleanup
------------

- Refactor background service handling into a library rather than repeating the same pattern multiple times inside the Nublado controller.

- Replace the arbitrary delays in the test suite with condition variables or Kubernetes mock watches.

- Get rid of the generic ``jupyterlabcontroller.util`` module.
  Catch-all utility modules should be broken up and their contents moved to more accurately named modules.

- Provide a cleaner way to construct a ``NodeImage`` from an ``RSPImage``.

- Use ``importlib.resources`` to get the form template.

- Switch to Ruff for linting.

Minor changes
-------------

- Use shorter names for internal components of lab pods, such as volumes and containers.
  These are specific to the pod and don't need to be namespaced like Kubernetes object names.

- Reconsider the labels and annotations that are added to created pods.

- Change lab extensions to use ``JUPYTER_IMAGE_SPEC`` instead of ``JUPYTER_IMAGE``.

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

- Implement timeouts and retries for Kubernetes calls, similar to what Kubespawner did, to make the controller more robust against temporary control plane problems.

New features
------------

- Add JupyterHub administrator permissions for members of ``g_admins`` so that we can use the JupyterHub UI and API.

- Support persistent volume claims for init containers for parallelism with the configuration for the regular lab.
  We currently have no use case for this, so this would currently only be for completeness and parallelism, but at present it looks like it's supported when it's not and would cause weird problems if used.

- Move Docker client code out of the Nublado controller and build an image pruner using the same basic code.

Minor changes
-------------

- Convince the semver package to use ``__all__`` at the top level so that mypy recognizes what symbols are exported and we don't have to import symbols from submodules.
