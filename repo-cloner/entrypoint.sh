#!/bin/sh

# repo-cloner
# -----------

# Shallow-clone a repository (specified in `$GIT_SRC`, branch
# `$GIT_BRANCH`) to a directory (`$GIT_TARGET`), or, if it already
# exists, update the branch.

# This is intended to be run as a Kubernetes CronJob to keep an on-disk
# shared copy of the tutorial notebooks fresh, so that a user Lab will not
# have to do its own clone on startup.

# It can, however, be used with any Git repository.

set -eou pipefail

# Print debugging output to ensure that we are running as who we think we
# are.

id

# Defaults
TARGET="${GIT_TARGET:-/project/cst_repos/tutorial-notebooks}"
SRC="${GIT_SRC:-https://github.com/lsst/tutorial-notebooks}"
BRANCH="${GIT_BRANCH:-main}"

# People committing to the branch may not have their umasks set
# correctly.  They should be working locally and pushing their changes
# and letting the cloner cronjob take care of doing the write, but
# evidently some people are just working directly in the repo.

force_permissions() {
    # Make everything group-writeable
    chmod -R g+w "${TARGET}"
    # Then make all directories setgid
    find "${TARGET}" -type d -print0 | xargs -0 chmod g+s
}

# If directory exists, pull the branch.
# Otherwise, shallow-clone the branch.
if [ -d "${TARGET}" ]; then
    cd "${TARGET}" ;
    force_permissions
    git checkout "${BRANCH}"
    git pull
    force_permissions
else
    cd $(dirname "${TARGET}")
    git clone --depth 1 -b "${BRANCH}" "${SRC}"
    force_permissions
fi
