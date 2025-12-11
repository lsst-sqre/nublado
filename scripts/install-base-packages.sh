#!/usr/bin/env bash
# This script updates packages in the base Docker image that's used by both the
# build and runtime images, and gives us a place to install additional
# system-level packages with apt-get.
#
# Based on the blog post:
# https://pythonspeed.com/articles/system-packages-docker/

# Bash "strict mode", to help catch problems and bugs in the shell
# script. Every bash script you write should include this. See
# http://redsymbol.net/articles/unofficial-bash-strict-mode/ for details.
set -euo pipefail

# Display each command as it's run.
set -x

# Tell apt-get we're never going to be able to give manual feedback.
export DEBIAN_FRONTEND=noninteractive

# Refresh package lists.

apt-get update

# Install security updates:

apt-get -y upgrade

# Emacs-nox and vim should cover most people's editing habits.
# Everything uses git to determine versions and to, in the case of the
#  cloner, do its real job.
# Psmisc gives us a bunch of useful tools, most notably "killall" and "fuser".
# Quota is helpful when debugging user filesystem issues.  The most common
#  problem is that the user has exceeded their quota.
# Rsync is invaluable for restarting huge copies, which is something we
#  have to do when migrating service.
# Screen and tmux so that you can easily have multiple shells open at
#  once.  My muscle memory is stuck on screen but tmux is much less obscure to
#  configure.

apt-get -y install \
    emacs-nox \
    git \
    psmisc \
    quota \
    rsync \
    screen \
    tmux \
    vim

