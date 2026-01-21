# Docker build instructions for the multifunction Nublado container.
#
# This Dockerfile has three stages:
#
# base-image
#   Updates the base Python image with security patches and common system
#   packages. This image becomes the base of all other images.
# install-image
#   Installs third-party dependencies and the application into a virtual
#   environment. This virtual environment is ideal for copying across
#   build stages.
# runtime-image
#   - Copies the virtual environment into place.
#   - Runs a non-root user.
#   - Sets up the entrypoint and port.

FROM python:3.14.2-slim-trixie AS base-image

# Install uv.
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /bin/uv

# Update already-installed packages and Install additional packages required
# (mostly by fsadmin)
COPY scripts/install-base-packages.sh .
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    ./install-base-packages.sh && rm install-base-packages.sh

FROM base-image AS install-image

# Install some additional packages required for building dependencies.
COPY scripts/install-dependency-packages.sh .
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    ./install-dependency-packages.sh

# Disable hard links during uv package installation since we're using a
# cache on a separate file system.
ENV UV_LINK_MODE=copy

# Install the dependencies.
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-default-groups --compile-bytecode --no-install-project

# Install the application itself.
ADD . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable --no-default-groups --compile-bytecode

WORKDIR /go
ADD golang /go
RUN make

FROM base-image AS runtime-image

# Create a non-root user.
RUN useradd --create-home appuser

# Copy the virtualenv.
COPY --from=install-image /app/.venv /app/.venv

# COPY the fileserver
COPY --from=install-image /go/worblehat /usr/local/bin

# Copy the repo-cloner for use in a CronJob context.
COPY assets/repo-cloner.sh /usr/local/bin

# FSadmin setup
# Copy screenrc for fsadmin; idiosyncratic but not a terrible default.
COPY assets/screenrc /etc/screenrc

# Make root use bash by default.  It's no longer 1983, why suffer?
RUN chsh -s /bin/bash root

# Switch to the non-root user.
USER appuser

# Expose the port.
EXPOSE 8080

# Make sure we use the virtualenv.
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH"

# No default CMD or ENTRYPOINT.

# For controller:
# CMD ["uvicorn", "nublado.controller.main:create_app", "--port", "8080", "--host", "0.0.0.0" ]
# For inithome:
# CMD ["nublado", "inithome"]
# For purger:
# CMD ["nublado", "purger", "execute"]
# For repo-cloner:
# CMD ["/usr/local/bin/repo-cloner.sh"]
# For landing page init container:
# CMD ["nublado", "landingpage"]
# For startup init container:
# CMD ["nublado", "startup"]
