# Change log

Nublado is versioned with [semver](https://semver.org/). Dependencies are updated to the latest available version during each release. Those changes are not noted here explicitly.

Find changes for the upcoming release in the project's [changelog.d directory](https://github.com/lsst-sqre/nublado/tree/main/changelog.d/).

<!-- scriv-insert-here -->

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
