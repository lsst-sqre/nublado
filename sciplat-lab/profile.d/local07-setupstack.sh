#!/bin/sh
if [ -n "${RUNNING_INSIDE_JUPYTERLAB}" ]; then
    . /opt/lsst/software/stack/loadLSST.bash
fi
