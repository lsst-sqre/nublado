# Nublado controller

This is the Kubernetes controller that manages Notebook Aspect resources in the Rubin Science Platform.
There are three fundamental functions, interrelated but distinct, that the controller provides:

* Spawning and lifecycle management of user Kubernetes lab pods
* Prepulling of desired images to nodes
* Spawning and lifecycle management of WebDAV file servers so that users can manipulate their files

The source for the Nublado controller follows the organization pattern described in [SQR-072](https://sqr-072.lsst.io).
It is developed with [FastAPI](https://fastapi.tiangolo.com) and [Safir](https://safir.lsst.io).
