#!/bin/sh
source ${LOADSTACK} && \
    conda install -y -c conda-forge mamba
source ${LOADSTACK} && \
    mamba install -y -c conda-forge \
      'jupyterlab=2' \
      jupyterhub \
      jupyter-server-proxy \
      jupyter-packaging \
      geoviews \
      cookiecutter \
      nbval \
      pyshp \
      pypandoc \
      astroquery \
      ipyevents \
      ipywidgets \
      ipyevents \
      bokeh \
      cloudpickle \
      ipympl \
      fastparquet \
      paramnb \
      ginga \
      bqplot \
      ipyvolume \
      papermill \
      'dask=2020.12' \
      gcsfs \
      snappy \
      'distributed=2020.12' \
      dask-kubernetes \
      "holoviews[recommended]" \
      datashader \
      python-snappy \
      graphviz \
      'mysqlclient!=2.0.2' \
      hvplot \
      intake \
      intake-parquet \
      jupyter-server-proxy \
      toolz \
      partd \
      nbdime \
      dask_labextension \
      numba \
      awkward \
      awkward-numba \
      swifter \
      pyvo \
      'jupyterlab_iframe<0.3' \
      astrowidgets \
      sidecar \
      python-socketio \
      pywwt \
      freetype-py \
      nodejs \
      terminado \
      "jedi<0.18.0"
source ${LOADSTACK} && \
      pip install --upgrade \
       lsst-efd-client \
       wfdispatcher \
       firefly-client \
       socketIO-client \
       rubin_jupyter_utils.lab \
       jupyterlab_hdf \
       jupyter_firefly_extensions \
       nbconvert[webpdf] \
       nclib \
       git+https://github.com/ericmandel/pyjs9
# Add stack kernel
source ${LOADSTACK} && \
      python3 -m ipykernel install --name 'LSST'
# Remove "system" kernel
ename="lsst-scipipe-0.1.5"
stacktop="/opt/lsst/software/stack/conda/current"
rm -rf ${stacktop}/envs/${ename}/share/jupyter/kernels/python3
