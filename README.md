# jupyterlab-controller (aka Nublado v3)

This is a controller for management of Notebook Aspect resources in the RSP.

The third attempt at our Notebook Aspect controller is defined in [SQR-066](https://sqr-066.lsst.io).
This is an implementation of that design.

There are three fundamental functions, interrelated but distinct, that the controller provides:

* Lab resource control
* Prepulling of desired images to nodes
* Construction of the options form supplied to the user by JupyterHub

## Source organization

The [source for the controller](https://github.com/lsst-sqre/jupyterlab-controller) follows the organization pattern described in [SQR-072](https://sqr-072.lsst.io).

The jupyterlab-controller application is developed with [FastAPI](https://fastapi.tiangolo.com) and [Safir](https://safir.lsst.io).
