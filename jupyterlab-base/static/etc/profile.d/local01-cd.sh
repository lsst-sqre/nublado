#!/usr/bin/env sh

# If we do not start JupyterLab from ${HOME}, this will ensure that we
# nevertheless start new shells in ${HOME}
if [ -d ${HOME} ]; then
    cd ${HOME}
