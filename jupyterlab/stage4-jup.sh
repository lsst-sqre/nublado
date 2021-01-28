#!/bin/sh
set -e
mkdir -p ${jl}
source ${LOADRSPSTACK}
for s in $SVXT; do \
    jupyter serverextension enable ${s} --py --sys-prefix ; \
done
for n in $NBXT; do \
    jupyter nbextension install ${n} --py --sys-prefix && \
    jupyter nbextension enable ${n} --py  --sys-prefix ; \
done
for l in ${LBXT}; do \
    jupyter labextension install ${l} --no-build ; \
done
# HDF5 viewer gonna take some work.
# Create package version docs.
# conda env export works where mamba env export does not
mkdir -p ${verdir} && \
      pip3 freeze > ${verdir}/requirements-stack.txt && \
      mamba list --export > ${verdir}/conda-stack.txt && \
      conda env export > ${verdir}/conda-stack.yml && \
      rpm -qa | sort > ${verdir}/rpmlist.txt
for l in ${LBXT} ; do \
    jupyter labextension enable ${l} ; \
done
jupyter labextension disable \
      "@jupyterlab/filebrowser-extension:share-file"
npm cache clean --force && \
      jupyter lab clean && \
      jupyter lab build --dev-build=False --minimize=False
jupyter labextension list 2>&1 | \
      grep '^      ' | grep -v ':' | grep -v 'OK\*' | \
      awk '{print $1,$2}' | tr ' ' '@' > ${verdir}/labext.txt
# Lab extensions require write permissions by running user.
# If we recursively chown all of the lab directory, it gets rid of permission
# errors on startup....but also radically slows down startup, by about
# three minutes.
groupadd -g 768 jovyan && \
     uls="/usr/local/share" && \
     jlb="jupyter/lab" && \
     u="${uls}/${jlb}" && \
     mkdir -p ${u}/staging ${u}/schemas ${u}/themes && \
     set -e && \
     for i in ${srcdir} ${u}/staging; do \
         chgrp -R jovyan ${i} && \
         chmod -R g+w ${i} ; \
     done
# Clear caches
rm -rf /tmp/* /tmp/.[0-z]* /root/.cache/pip && \
      yum clean all
