#!/bin/bash
#
# This script updates any apt packages in the base container for security
# fixes and installs additional packages used either when installing
# dependencies or at runtime.

# Bash "strict mode", to help catch problems and bugs in the shell
# script. Every bash script you write should include this. See
# http://redsymbol.net/articles/unofficial-bash-strict-mode/ for details.
set -euo pipefail

# Display each command as it's run.
set -x

# Tell apt-get we're never going to be able to give manual feedback.
export DEBIAN_FRONTEND=noninteractive

# Update the package listing, so we know what packages exist.
apt-get update

# Install various dependencies that may be required to install JupyterHub or
# our add-on modules, or are wanted at runtime:
#
# build-essential: sometimes needed to build Python modules
# git: required by setuptools_scm
# libffi-dev: sometimes needed to build cffi, a cryptography dependency
# libpq-dev, python3-dev: required to build psycopg2
# postgresql-client: for interactive use to look at the session database
#
# postgresql-client is not strictly necessary, but if we're using CloudSQL
# proxy against a Cloud SQL instance that has no public IP and a network
# policy only allowing access to the proxy from the Hub pod, this is a much
# easier way to inspect the database than an interactive Python session.
apt-get -y install --no-install-recommends build-essential git libffi-dev \
    libpq-dev python3-dev postgresql-client

# Delete cached files we don't need anymore.
apt-get clean
rm -rf /var/lib/apt/lists/*
