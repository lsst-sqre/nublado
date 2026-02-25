<<<<<<< HEAD:jupyterlab-base/static/etc/profile.d/local01-cd.sh
#!/usr/bin/env sh

# If we do not start JupyterLab from ${HOME}, this will ensure that we
# nevertheless start new shells in ${HOME}
if [ -d ${HOME} ]; then
    cd ${HOME}
=======
#!/bin/sh
if [ -n "${HOME}" ];
   cd "${HOME}"
>>>>>>> 303e851b (Force cd to homedir in login shell):jupyterlab-base/profile.d/local01-cd.sh
fi
