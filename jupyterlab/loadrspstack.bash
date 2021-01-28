# This script is intended to be used with bash to load the RSP clone of
#  the minimal LSST environment
# Usage: source loadrspstack.bash

export LSST_CONDA_ENV_NAME="rsp-$(source ${LOADSTACK} && \
                 echo "${LSST_CONDA_ENV_NAME}")"
# shellcheck disable=SC1091
source "/opt/lsst/software/stack/conda/miniconda3-py38_4.9.2/etc/profile.d/conda.sh"
conda activate "$LSST_CONDA_ENV_NAME"
LSST_HOME="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

export EUPS_PATH="/opt/lsst/software/stack/stack/miniconda3-py38_4.9.2-0.1.5"
export EUPS_PKGROOT=${EUPS_PKGROOT:-https://eups.lsst.codes/stack/redhat/el7/conda-system/miniconda3-py38_4.9.2-0.1.5}
