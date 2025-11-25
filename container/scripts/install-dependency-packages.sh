#!/usr/bin/env bash
# Bash "strict mode", to help catch problems and bugs in the shell
# script. Every bash script you write should include this. See
# http://redsymbol.net/articles/unofficial-bash-strict-mode/ for details.
set -euo pipefail

# Display each command as it's run.
set -x

# Tell apt-get we're never going to be able to give manual feedback.
export DEBIAN_FRONTEND=noninteractive

apt-get update

# These are needed for building the Nublado controller, but not at runtime.

apt-get -y install --no-install-recommends \
    build-essential \
    libffi-dev \
    libz-dev
