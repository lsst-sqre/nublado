# Change log

Nublado is versioned with [semver](https://semver.org/). Dependencies are updated to the latest available version during each release. Those changes are not noted here explicitly.

Find changes for the upcoming release in the project's [changelog.d directory](https://github.com/lsst-sqre/nublado/tree/main/changelog.d/).

<!-- scriv-insert-here -->

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
