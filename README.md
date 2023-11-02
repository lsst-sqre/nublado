# Nublado

Nublado (taken from the Spanish word for cloud) provides the user notebook service and related user-spawned Kubernetes pods for the Rubin Science Platform.
Currently, it provides authentication and lab pod spawning for user science notebooks and WebDAV-based file servers so that users can easily manipulate their files.

For full documentation, see [nublado.lsst.io](https://nublado.lsst.io).

For more information about the current Nublado Kubernetes controller design, see [SQR-066](https://sqr-066.lsst.io).

## Source organization

This repository uses the vertical monorepo layout described in [SQR-075](https://sqr-075.lsst.io).
It uses [nox](https://nox.thea.codes/en/stable/) as its build system, since nox works better with monorepos than the build systems used by other Rubin Science Platform projects.

For details on how to use the development repository, see [the development guide](https://nublado.lsst.io/dev/development.html).
