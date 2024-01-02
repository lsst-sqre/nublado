# Change log

Nublado is versioned with [semver](https://semver.org/). Dependencies are updated to the latest available version during each release. Those changes are not noted here explicitly.

Find changes for the upcoming release in the project's [changelog.d directory](https://github.com/lsst-sqre/nublado/tree/main/changelog.d/).

<!-- scriv-insert-here -->

## 4.0.0 (2024-01-02)

This is the first release of the new merged Nublado release. It contains the Nubaldo controller, a JupyterHub spawner implementation that uses the controller to create user labs, a JupyterHub authenticator implementation to use [Gafaelfawr](https://gafaelfawr.lsst.io/), and the Docker configuration to build a custom JupyterHub image containing that spawner and authenticator.

In previous versions of Nublado, the equivalents of these components were maintained in separate repositories with independent version numbers.
As of this release, all of these components are maintained and released together using semver versioning.
Further changes will be documented in this unified change log.
