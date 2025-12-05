#!/usr/bin/env bash
set -x
set -euo pipefail
# Install lsst-rsp, which contains the entrypoints we need for both the
# landing page provisioner and the RSP init container.
#
# Don't bother with a venv: things in lsst-rsp are the only reason you'd
# run this container.

uv pip install --system 'git+https://github.com/lsst-sqre/lsst-rsp'

# Increase this to build a new version when we have a new lsst-rsp.  Reset
# if anything else in this file changes.
# Serial: 0
