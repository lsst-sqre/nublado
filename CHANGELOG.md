# Change log

Nublado is versioned with [semver](https://semver.org/). Dependencies are updated to the latest available version during each release. Those changes are not noted here explicitly.

Find changes for the upcoming release in the project's [changelog.d directory](https://github.com/lsst-sqre/nublado/tree/main/changelog.d/).

<!-- scriv-insert-here -->

<a id='changelog-8.17.0'></a>
## 8.17.0 (2025-10-14)

### New features

- Use Repertoire service discovery in the JupyterHub spawner plugin to find the Nublado controller API.
- Enable Sentry and Slack error reporting in the file purger.

### Bug fixes

- Support pagination when listing the tags for lab images from a Docker repository in the Nublado controller. This is required when using GitHub Container Registry as an image source if there are a significant number of image tags.
- Send the correct `Accept` header when requesting container checksums from a Docker registry that may contain multi-architecture images.
- Ignore prepuller updates for nodes that no longer exist instead of raising uncaught exceptions and pausing the prepuller.

<a id='changelog-8.16.0'></a>
## 8.16.0 (2025-10-08)

### New features

- Mount [Repertoire](https://repertoire.lsst.io/) discovery information at `/etc/nublado/discovery/v1.json` in user notebook pods.
- Use Repertoire service discovery to find the logout URL for the JupyterHub Gafaelfawr plugin.
- Export of notebooks to PDF in the jupyterlab-base image now uses TeX instead of Chromium, which shrinks the size of the image by over 1GiB.
- Instrument client exceptions with Sentry metadata.

### Bug fixes

- Always use `user` for the username in logging contexts, and include username in more log messages.
- Filter out platform-specific tags from the spawner menu when corresponding generic tag exists.

### Other changes

- The jupyterlab-base image is now based on the Debian trixie release.
- Use [uv workspaces](https://docs.astral.sh/uv/concepts/projects/workspaces/) and [uv lock files](https://docs.astral.sh/uv/concepts/projects/sync/) to manage packages and dependencies.

<a id='changelog-8.15.0'></a>
## 8.15.0 (2025-09-16)

### New features

- Optionally report Nublado controller errors to Sentry.

<a id='changelog-8.14.0'></a>
## 8.14.0 (2025-09-11)

### New features

- Resource requests for user lab pods can (and must) be specified explicitly. Before this change, only resource limits were specified and requests were calculated to be 1/4 of the limits. The `controller.config.lab.sizes` entries now have a different format.

  Old:

  ```yaml
  sizes:
    - size: "small"
      cpu: 1.0      # This was a limit
      memory: "4Gi" # This was a limit
  ```

  New:

  ```yaml
  sizes:
    - size: "small"
      resources:
        limits:
          cpu: 1.0
          memory: "4Gi"
        requests:
          cpu: 0.25
          memory: "0.75Gi"
  ```

### Bug fixes

- Push the purger Docker image to the correct Google Artifact Registry rather than overwriting the inithome container.

<a id='changelog-8.13.1'></a>
## 8.13.1 (2025-08-28)

### Other changes

- Adopt updated Safir.

<a id='changelog-8.13.0'></a>
## 8.13.0 (2025-08-28)

### New features

- Added Nublado controller route to control administrative filesystem pod. This allows a user with an admin token to spawn a pod that mounts user file systems with administrative privileges. That pod can then be entered by the administrator with `kubectl exec` for remedial or forensic purposes.	The pod can also be deleted through this route, and the status of the pod can be queried.

### Bug fixes

- Install ipython-genutils in jupyterlab-base since ipympl has an implicit dependency on it.

<a id='changelog-8.12.2'></a>
## 8.12.2 (2025-08-15)

### Other changes

- Rebuild jupyterlab-base with newer dependencies.

<a id='changelog-8.12.1'></a>
## 8.12.1 (2025-08-07)

### Bug fixes

- Improve handling of exceptions in the notebook execution extension.

<a id='changelog-8.12.0'></a>
## 8.12.0 (2025-08-07)

### New features

- Include `.config` in the list of directories moved aside when the user asks to reset their user environment.

<a id='changelog-8.11.0'></a>
## 8.11.0 (2025-08-01)

### New features

- Add a build number as an optional portion of the image tag format.

### Bug fixes

- Fix the link to the WebDAV documentation in the HTML page returned after a user's file server was started.

<a id='changelog-8.10.0'></a>
## 8.10.0 (2025-07-16)

### New features

- Add a cron job to purge file systems of old files. This was formerly maintained in the lsst-sqre/rsp-scratchpurger repository.

<a id='changelog-8.9.2'></a>
## 8.9.2 (2025-07-02)

### Bug fixes

- Accept group names from Gafaelfawr that start with digits as long as they contain at least one letter. Group names of that type can arise from per-user groups for users with a username starting with a digit.

<a id='changelog-8.9.1'></a>
## 8.9.1 (2025-06-28)

### Bug fixes

- Rebuild jupyterlab-base with lsst-rsp 0.9.4, which fixes a bug in overquota handling when a welcome page is configured and presents a better overquota landing page.

<a id='changelog-8.9.0'></a>
## 8.9.0 (2025-06-26)

### New features

- Add new `controller.config.lab.defaultSize` configuration option that determines the default lab size in the spawner menu. If not set, or set to a lab size the user does not have sufficient quota to spawn, the default continues to be the first size the user is allowed to spawn.
- Add `controller.config.fileserver.reconcileInterval` configuration option to control the frequency with which file server state is reconciled with Kubernetes.
- Add `controller.config.lab.reconcileInterval` configuration option to control the frequency with which lab state is reconciled with Kubernetes.
- Add `controller.config.images.refreshInterval` configuration option to control how often the image source is checked for new images and the Kubernetes nodes are checked for the list of cached images.

### Bug fixes

- Fix a race condition during file server Kubernetes reconciliation where a file server in the process of being created, but waiting for the ingress to become valid, could be deleted by the background reconciliation job.
- Fix background task timing with very short intervals. This will probably never arise in a production configuration but was triggered by the test suite.

<a id='changelog-8.8.9'></a>
## 8.8.9 (2025-06-23)

### Bug fixes

- Simplify the HTML page shown after the user spawns a file server and point to the RSP documentation.
- Standardize on `write:files` as the scope for accessing the file server. This was already required to spawn the file server, but `exec:notebook` was still used to control access to the spawned file server.

<a id='changelog-8.8.8'></a>
## 8.8.8 (2025-06-16)

### Bug fixes

- Update JupyterHub to 5.3.0 (Zero to JupyterHub 4.2.0).

<a id='changelog-8.8.7'></a>
## 8.8.7 (2025-06-11)

### Other changes

- Document how to customize Nublado JupyterLab behavior.

<a id='changelog-8.8.6'></a>
## 8.8.6 (2025-05-21)

### New features

- Update the base Jupyter Lab extensions to support specifying the kernel to use via the `/execution` endpoint.

### Bug fixes

- Fix builds when `jupyter labextension list` exits with a non-zero status.

<a id='changelog-8.8.5'></a>
## 8.8.5 (2025-05-16)

### Bug fixes

- When building the list of available lab images, only include versions from tags on the lab image name, not other Docker images in the same repository.

<a id='changelog-8.8.4'></a>
## 8.8.4 (2025-04-28)

### New features

- When tagging jupyterlab-base for a new release, also move the `latest` tag to the new release.

<a id='changelog-8.8.3'></a>
## 8.8.3 (2025-04-23)

### New features

- Add `less` to the base JupyterLab container image.

### Bug fixes

- Fix the install locations of configuration files in the base JupyterLab container image.

<a id='changelog-8.8.2'></a>
## 8.8.2 (2025-04-03)

### Bug fixes

- Push inithome containers to Google as well as GitHub since GitHub has a low rate limit on anonymous API requests.

### Other changes

- Update jupyterlab-server in the base JupyterLab container image.

<a id='changelog-8.8.1'></a>
## 8.8.1 (2025-03-27)

### Bug fixes

- Fix uploads of `rubin-nublado-client` to PyPI.

<a id='changelog-8.8.0'></a>
## 8.8.0 (2025-03-25)

### New features

- Support setting the interval for activity reporting from JupyterLab in the Nubaldo controller configuration.

### Bug fixes

- Add a configuration setting for where to redirect the user after logout from JupyterHub. When user subdomains are in use, this needs to point to `/logout` at the base URL for the Science Platform, not `/logout` at the current hostname, which may be the JupyterHub hostname and thus create an infinite redirect loop.
- Use the configured delete timeout when deleting invalid labs instead of a hard-coded 30s timeout.

<a id='changelog-8.7.1'></a>
## 8.7.1 (2025-03-19)

### Bug fixes

- Fix the `NetworkPolicy` created for user labs so that it actually restricts access to only JupyterHub, its proxy, and the lab itself as was intended.

<a id='changelog-8.7.0'></a>
## 8.7.0 (2025-03-17)

### New features

- Add support for per-user subdomains to the Nublado client. If they are enabled, they will be automatically detected and the Nublado client will adjust its HTTP requests accordingly.
- Add support to the Nublado client testing mocks for simulating per-user subdomains.
- Add `config.allowOptions` to the `GafaelfawrIngress` for file servers so that the server will work correctly with Gafaelfawr 13.0.0 and later.

### Bug fixes

- Set `Sec-Fetch-Mode` in several places in the Nublado client to suppress harmless but annoying warnings in the JupyterHub logs.

<a id='changelog-8.6.0'></a>
## 8.6.0 (2025-02-26)

### New features

- Add support to the Nublado controller for restricting the list of images shown in the dropdown menu based on age, count within a category, or a version cutoff.

### Bug fixes

- Fix an unbound variable error in the Nublado client in one error handling situation.

<a id='changelog-8.5.0'></a>
## 8.5.0 (2025-02-24)

### Other changes

- Raise the upper bound on the Safir in the Nublado client to `<11`.

<a id='changelog-8.4.2'></a>
## 8.4.2 (2025-02-19)

### Bug fixes

- Fix `TypeError` exception when trying to establish websocket connections. Version 14 of [websockets](https://websockets.readthedocs.io/en/stable/) [changed the signature of the `connect` method](https://websockets.readthedocs.io/en/stable/howto/upgrade.html#extra-headers-additional-headers).

<a id='changelog-8.4.1'></a>
## 8.4.1 (2025-02-12)

### Bug fixes

- Wait for the default service account of the user's lab namespace to be created before creating the `Pod` object. Creation of the service account can be slow when Kubernetes is busy, and creation of the `Pod` object will fail if the service account does not exist.
- Remove the limit on the connection pool used to contact the Nublado controller from the JupyterHub spawner, since otherwise JupyterHub stops being able to do any work once the connections waiting for spawn progress exhaust the connect pool.
- Remove the limit on the Kubernetes client connection pool in the Nublado controller. This will allow the controller to scale to more than 100 (the default) simultaneous watches.
- Remove the limit on the connection pool used to look up users in Gafaelfawr and query a Docker image repository.
- Fix unsafe data structure manipulation when deleting completed labs in the Nublado controller background reconciliation thread.

<a id='changelog-8.4.0'></a>
## 8.4.0 (2025-02-04)

### New features

- Log metrics events in the Nublado controller for lab spawn successes and failures and a count of the number of active labs.

### Bug fixes

- Do not query Kubernetes for pod status when responding to status requests, and instead assume the internal state (which is reconciled periodically) is correct. The constant Kubernetes API requests for `Pod` status seemed to be overwhelming the control plane when there were a lot of pods running. Continue to ask Kubernetes directly immediately before spawn.
- Report Kubernetes operation timeouts properly when they cause a spawn failure rather than throwing an uncaught exception.
- Add tolerations to prepuller pods as well as lab and file server pods so that images can be prepulled to tainted nodes.

<a id='changelog-8.3.0'></a>
## 8.3.0 (2025-01-24)

### New features

- Support the new `spawn` flag in the user's Gafaelfawr metadata. If set to false, tell the user that spawns aren't allowed rather than presenting a menu and reject spawns in the Nublado controller with a 403 error.

### Bug fixes

- Return a spawner form showing only an error rather than an HTTP failure if the user's quota does not allow them to spawn any of the configured notebook sizes.

### Other changes

- Drop support for Gafaelfawr groups without GIDs. Gafaelfawr has required all groups have GIDs since Gafaelfawr 11.0.0.
- Add documentation explaining how to use node selection and recommending `nodeSelector` over `affinity`.

<a id='changelog-8.2.0'></a>
## 8.2.0 (2024-12-12)

### New features

- Add a `service` label to `GafaelfawrIngress` resources created for user file servers for proper Gafaelfawr metrics reporting.

### Other changes

- Change the base image for JupyterHub to `quay.io/jupyterhub/k8s-hub` from `jupyterhub/jupyterhub`. This means the JupyterHub image now uses Python 3.12.

<a id='changelog-8.1.0'></a>
## 8.1.0 (2024-12-12)

### Bug fixes

- Remove the `Token` link from the JupyterHub page template, since user tokens for JupyterHub are not supported on the Rubin Science Platform.

### Other changes

- Update to JupyterHub 5.2.1.

<a id='changelog-8.0.3'></a>
## 8.0.3 (2024-11-18)

### Bug fixes

- When reporting HTTP errors from the Nublado client, truncate the response body at the start rather than at the end. This makes it more likely that the error message from JupyterHub will appear in the truncated response.
- Drop the XSRF token and cookies before performing a JupyterHub login in the Nublado client. The client previously hung on to the XSRF token indefinitely, which resulted in errors if the token was expired in JupyterHub, such as by user session expiration.

<a id='changelog-8.0.2'></a>
## 8.0.2 (2024-10-31)

### Bug fixes

- Fix broken formatting in error messages reported by the Nublado client.

<a id='changelog-8.0.1'></a>
## 8.0.1 (2024-10-31)

### Bug fixes

- Improve error reporting of exceptions in the Nublado client and sanitize the reported body to remove some security tokens.

<a id='changelog-8.0.0'></a>
## 8.0.0 (2024-10-22)

### Backwards-incompatible changes

- Refactor exception handling in `NubladoClient` to incorporate optional code context information (used by [mobu](https://mobu.lsst.io/)) and additional exception metadata.

### New features

- Provide `JupyterLabSession` as an exported class from `rubin.nublado.client`. This class represents an open WebSocket session with a Jupyter lab.
- Add support for artificial Gafaeflawr tokens to the `MockJuypter` mock of the JupyterHub and JupyterLab API. This allows the mock to extract a username from mock tokens sent by the code under test to the mocked APIs, rather than requiring the test client send an `X-Auth-Request-User` header.
- Use the most recent Nublado release tag as the default base image for sciplat-lab container builds.

<a id='changelog-7.2.0'></a>
## 7.2.0 (2024-10-01)

### New features

- Add a Docker image build for a `jupyterlab-base` image, which provides a basic image that can be spawned as a lab container by Nublado and can be used as the basis for more complex images.
- Add the Docker image build for `sciplat-lab`, an image built on top of `jupyterlab-base` that provides a JupyterLab kernel that includes the Rubin Science Pipelines Python stack.

### Bug fixes

- Revert canonical PyPI module name back to `rubin-nublado-client` for consistency with other projects. As before, this change should not affect `pip install`; either form of the name should work.

<a id='changelog-7.1.2'></a>
## 7.1.2 (2024-09-23)

### Bug fixes

- Rename PyPI module for the Nublado client to `rubin.nublado.client`. Either name should work for `pip install`.

<a id='changelog-7.1.1'></a>
## 7.1.1 (2024-09-23)

### Bug fixes

- Push the new `rubin-nublado-client` module to PyPI on release.

<a id='changelog-7.1.0'></a>
## 7.1.0 (2024-09-23)

### New features

- Add the Python module `rubin-nublado-client`, which provides a client library for interacting with the Nublado-modified JupyterHub and JupyterLab services.

<a id='changelog-7.0.0'></a>
## 7.0.0 (2024-08-19)

### Backwards-incompatible changes

- The `/tmp` directory in a lab pod now defaults to a tmpfs file system capped at 25% of the pod memory. Add a new configuration option to select between this default and the previous default of uncapped node-local storage.

<a id='changelog-6.3.0'></a>
## 6.3.0 (2024-08-15)

### New features

- All timeout configuration options now support the syntax parsed by Safir's `parse_timedelta` and therefore support human-friendly durations such as `6h` or `5m`.

### Bug fixes

- Fix crash of the controller during startup if a Kubernetes node reports a cached image with no names.
- Fix bootstrapping of a development environment in an existing virtualenv. Previously, uv was not installed before nox attempted to use it.
- Work around a bug in sphinxcontrib-redoc that prevented building the documentation twice without errors.

<a id='changelog-6.2.0'></a>
## 6.2.0 (2024-06-13)

### New features

- Add configuration settings for the lab launch command and configuration directory.

<a id='changelog-6.1.0'></a>
## 6.1.0 (2024-06-06)

### New features

- Add limits and requests to prepulled pods.

### Other changes

- Update the underlying JupyterHub implementation to JupyterHub 5.0.0.
- Switch to [uv](https://github.com/astral-sh/uv) for package management.

<a id='changelog-6.0.2'></a>
## 6.0.2 (2024-04-18)

### Bug fixes

- Update JupyterHub to 4.1.5, which fixes more issues with XSRF handling.
- Move the `.eups` directory when performing user environment resets.

<a id='changelog-6.0.1'></a>
## 6.0.1 (2024-04-01)

### Bug fixes

- Update JupyterHub to 4.1.4, which fixes more XSRF cookie issues.

<a id='changelog-6.0.0'></a>
## 6.0.0 (2024-03-28)

### Backwards-incompatible changes

- Move the admin route for deleting a user's file server from `/nublado/fileserver/v1/<username>` to `/nublado/fileserver/v1/users/<username>` to better align with other routes and REST semantics.

### New features

- Add an admin-authenticated `/nublado/fileserver/v1/users/<username>` GET route to get the status of a user's running file server (currently only 404 if not running or 200 with trivial content if running).
- Add a `/nublado/fileserver/v1/user-status` route a user to get the status of their own file server, which similarly returns 404 or 200 with trivial content.

### Bug fixes

- Update JupyterHub to 4.1.3, which includes several fixes for XSRF handling.

<a id='changelog-5.0.0'></a>
## 5.0.0 (2024-03-21)

### Backwards-incompatible changes

- Update to JupyterHub 4.1.0. This release has tighter XSRF handling than previous versions. Clients that talk directly to JupyterHub rather than using a browser, such as [mobu](https://github.com/lsst-sqre/mobu) or [Noteburst](https://noteburst.lsst.io/), will need to be updated to support the stricter XSRF requirements.

### Other changes

- Nublado now uses [uv](https://github.com/astral-sh/uv) to maintain frozen dependencies.

<a id='changelog-4.0.2'></a>
## 4.0.2 (2024-01-19)

### Bug fixes

- Update to Safir 5.2.0, which rewrites the middleware to avoid the Starlette `BaseHTTPMiddleware` class. This should hopefully produce better error reporting in some cases where exceptions were being mangled and lost by the `BaseHTTPMiddleware` logic.

<a id='changelog-4.0.1'></a>
## 4.0.1 (2024-01-12)

### Bug fixes

- All user file servers are now protected by a `NetworkPolicy` that prevents connections except via Gafaelfawr, ensuring that authentication is properly enforced.
- Stop returning the requested lab environment from the lab status API. Nothing uses this information and it may contain secrets that should not be this readily accessible.
- Return the actual running Docker image reference from the lab status API rather than the form parameters the user sent when requesting a lab.
- Return prepuller configuration in the API response with snake-case fields rather than camel-case fields, as was originally intended.
- Restrict access to controller routes via the `admin:jupyterlab` scope to only those routes that JupyterHub needs to use. Access to other administrative routes is now controlled with `exec:admin`.
- Fix the response type for the `/spawner/v1/labs/{username}/events` route in the OpenAPI schema.
- Quietly retry the file server pod watch after 410 errors, since under some circumstances they appear to happen every five minutes. Remove the delay when restarting after a 410 error without a resource version, since this appears to be a normal Kubernetes API response and the delay could miss events.

### Other changes

- Change the default Argo CD application for user file servers to `nublado-fileservers`. Continue to use `fileservers` as the default namespace, since the `nublado-fileservers` namespace would conflict with the reserved namespace pattern for user labs.
- Classify the JSON API routes with tags that reflect who has access to that API.
- Add documentation on how to set up Google Artifact Registry as an image source for Nublado, and on why this is the recommended configuration when Nublado is running on Google Kubernetes Engine.

## 4.0.0 (2024-01-02)

This is the first release of the new merged Nublado release. It contains the Nubaldo controller, a JupyterHub spawner implementation that uses the controller to create user labs, a JupyterHub authenticator implementation to use [Gafaelfawr](https://gafaelfawr.lsst.io/), and the Docker configuration to build a custom JupyterHub image containing that spawner and authenticator.

In previous versions of Nublado, the equivalents of these components were maintained in separate repositories with independent version numbers.
As of this release, all of these components are maintained and released together using semver versioning.
Further changes will be documented in this unified change log.
