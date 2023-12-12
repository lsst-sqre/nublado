#!/bin/bash
#
# This script installs additional packages used by the dependency image but
# not needed by the runtime image, such as additional packages required to
# build Python dependencies or install the Python package.

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

# Install git, which is required by setuptools_scm to get a correct version
# number when the package is installed.
apt-get -y install --no-install-recommends git

# Delete cached files we don't need any more to reduce the layer size.
apt-get clean
rm -rf /var/lib/apt/lists/*
