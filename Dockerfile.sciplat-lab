ARG input
FROM $input AS base-image
USER 0:0
SHELL ["/bin/bash", "-lc"]

RUN mkdir -p /tmp/build
WORKDIR /tmp/build

# Add other system-level files

# An /etc/passwd

COPY scripts/make-root-user /tmp/build
RUN ./make-root-user

# /etc/profile.d parts

RUN mkdir -p /etc/profile.d

COPY profile.d/local06-showrspnotice.sh profile.d/local07-setupstack.sh \
     /etc/profile.d/

# /etc/skel

RUN for i in notebooks WORK DATA; do mkdir -p /etc/skel/${i}; done

COPY skel/gitconfig /etc/skel/.gitconfig
COPY skel/git-credentials /etc/skel/.git-credentials
COPY skel/user_setups /etc/skel/notebooks/.user_setups

COPY runtime/lsst_kernel.json \
       /usr/local/share/jupyter/kernels/lsst/kernel.json

COPY etc/rsp_notice /usr/local/etc

FROM base-image AS user-image

# Add our user again (base image removes /etc/passwd)

COPY scripts/make-user /tmp/build
RUN ./make-user

USER lsst_local:lsst_local

# Add the DM stack.

FROM user-image AS base-stack-image
ARG tag

COPY scripts/install-dm-stack /tmp/build
RUN ./install-dm-stack $tag

COPY --chown=lsst_local:lsst_local etc/rsp_notice etc/20-logging.py \
     /usr/local/share/jupyterlab/etc/

COPY --chown=lsst_local:lsst_local runtime/lsst_kernel.json \
    runtime/lsstlaunch.bash /usr/local/share/jupyterlab/

COPY scripts/install-rsp-user /tmp/build
RUN ./install-rsp-user

FROM base-stack-image AS notebooks-rsp-image

# Check out notebooks-at-build-time
COPY scripts/install-notebooks /tmp/build
RUN ./install-notebooks

FROM notebooks-rsp-image AS compat-rsp-image

# Add compatibility layer to allow for transition from old to new
# paths.

COPY scripts/install-compat /tmp/build
RUN ./install-compat

FROM compat-rsp-image AS manifests-rsp-image

# Get our manifests.  This has always been really useful for debugging
# "what broke this week?"

COPY scripts/generate-versions /tmp/build
RUN ./generate-versions

FROM manifests-rsp-image AS rsp-image
ARG version

# Clean up.
# This needs to be numeric, since we will remove /etc/passwd and friends
# while we're running.
USER 0:0
WORKDIR /

COPY scripts/cleanup-files /
RUN ./cleanup-files
RUN rm ./cleanup-files

# Back to unprivileged
USER 1000:1000
WORKDIR /tmp

CMD ["/usr/local/share/jupyterlab/runlab"]

# Overwrite Stack Container definitions with more-accurate-for-us ones
ENV  DESCRIPTION="Rubin Science Platform Notebook Aspect"
ENV  SUMMARY="Rubin Science Platform Notebook Aspect"

LABEL description="Rubin Science Platform Notebook Aspect: $version" \
       name="sciplat-lab:$version" \
       version="$version"
