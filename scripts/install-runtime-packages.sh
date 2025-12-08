#!/usr/bin/env bash
# Bash "strict mode", to help catch problems and bugs in the shell
# script. Every bash script you write should include this. See
# http://redsymbol.net/articles/unofficial-bash-strict-mode/ for details.
set -euo pipefail

# Display each command as it's run.
set -x

# Tell apt-get we're never going to be able to give manual feedback.
export DEBIAN_FRONTEND=noninteractive

# These are for fsadmin, except git-lfs, which is part of the RSP startup
# process.
#
# Everyone uses git.

apt-get update

apt-get -y install \
    screen \
    tmux \
    git \
    git-lfs \
    rsync \
    emacs-nox \
    vim \
    psmisc \
    sudo \
    quota

# Delete cached files we don't need any more to reduce the layer size.
apt-get clean
rm -rf /var/lib/apt/lists/*
