# Nublado

Nublado (taken from the Spanish word for cloud) provides the user notebook service and related user-spawned Kubernetes pods for the Rubin Science Platform.
Currently, the Nublado controller provides authentication and lab pod spawning for user science notebooks and WebDAV-based file servers so that users can easily manipulate their files.
This and other functional components are described below.

For full documentation, see [nublado.lsst.io](https://nublado.lsst.io).

For more information about the current Nublado Kubernetes controller design, see [SQR-066](https://sqr-066.lsst.io).

## Source organization

This repository uses the vertical monorepo layout described in [SQR-075](https://sqr-075.lsst.io).
It uses [nox](https://nox.thea.codes/en/stable/) as its build system, since nox works better with monorepos than the build systems used by other Rubin Science Platform projects.

For details on how to use the development repository, see [the development guide](https://nublado.lsst.io/dev/development.html).

## Components

All these components run as subcommands of the `nublado` command.

### Controller

This is the Kubernetes controller that manages Notebook Aspect resources in the Rubin Science Platform.
There are three fundamental functions, interrelated but distinct, that the controller provides:

* Spawning and lifecycle management of user Kubernetes lab pods
* Prepulling of desired images to nodes
* Spawning and lifecycle management of WebDAV file servers so that users can manipulate their files

The source for the Nublado controller follows the organization pattern described in [SQR-072](https://sqr-072.lsst.io).
It is developed with [FastAPI](https://fastapi.tiangolo.com) and [Safir](https://safir.lsst.io).

### Inithome

This runs with privilege to create a user home directory and set appropriate permissions on it.
It is only for use at sites that allow the user home filesystem to be mounted as root and which do not have more elaborate user provisioning mechanisms.

### Purger

This implements a filesystem purging policy.  This is used in the RSP on the `/deleted-weekly` shares and must run with privilege.
Although in the RSP it simply deletes everything from those shares each week, it is capable of more sophisticated purging policies, should that be useful at some point.

### Startup

This provides the setup to provide the context in which to launch an RSP JupyterLab instance.
It should run as the same user as the Lab will.

## File system administration

If the container containing `nublado` is run with privilege, and it is in a context where the user has permissions to act as root on external filesystems (that is, `nublado inithome` could be used), and the user gets a root shell on it, then there are sufficient tools present to allow administrative filesystem tasks (that is, a small choice of editors, rsync, quota, screen, and tmux) to be completed.
Further, the user can use `apt` to install other packages at will, although of course these changes will be lost on container teardown.
