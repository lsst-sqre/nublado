jupyterlab-base
===============

This produces a container that includes Python 3 and JupyterLab, and can
be launched from the RSP Hub.

It does not include a DM Stack, or indeed any sort of payload Python
environment (as described in [sqr-088](https://sqr-088.lsst.io).

Insofar as feasible, Rubin-specific features have been removed.

The intention is for this container to be used as a base layer on top of
which payload environments will be overlaid, such as the DM stack.

