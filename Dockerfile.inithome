# Docker build instructions for the Nublado homedir provisioner (inithome).
#
# This Docker image creates and sets ownership of the user's home directory
# and is intended to be run as a Nublado lab init container. It is intended
# for environments that do not pre-create user home directories, or that do
# but want the lab home directory to be a subdirectory of the user's normal
# home directory.
#
# Since it runs as an init container on every spawn, we want to keep the image
# small. It therefore does not update base image packages for security fixes
# and instead relies on the Python container itself being rebuilt periodically
# with new minor versions of Python, which will result in PRs from Dependabot.
#
# This Dockerfile has two stages:
#
# install-image
#   - Installs git so that setuptools_scm can install the app.
#   - Installs the app into the virtual environment.
# runtime-image
#   - Copies the virtual environment into place.
#   - Sets up the entrypoint.

# This is just an alias to avoid repeating the base image.
FROM python:3.13.2-slim-bookworm AS base-image

FROM base-image AS install-image

# Install uv.
COPY --from=ghcr.io/astral-sh/uv:0.5.8 /uv /bin/uv

# Install system packages only needed for building dependencies or installing
# the package.
COPY inithome/scripts/install-dependency-packages.sh .
RUN ./install-dependency-packages.sh

# Create a Python virtual environment.
ENV VIRTUAL_ENV=/opt/venv
RUN uv venv $VIRTUAL_ENV

# Ensure we use the virtualenv.
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Install inithome.
COPY . /workdir
WORKDIR /workdir
RUN uv pip install --compile-bytecode --no-cache ./inithome

FROM base-image AS runtime-image

# Copy the virtualenv.
COPY --from=install-image /opt/venv /opt/venv

# Make sure we use the virtualenv.
ENV PATH="/opt/venv/bin:$PATH"

# Run the application.
CMD ["inithome"]
