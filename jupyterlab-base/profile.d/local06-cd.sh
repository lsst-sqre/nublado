#!/bin/sh
# The terminal should start in $HOME even if that's not where JupyterLab
# started.
if [ "${FILEBROWSER_ROOT}" == "root" ]; then
    cd "${HOME}"
fi
