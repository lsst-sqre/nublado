"""Constants for RSP startup."""

from pathlib import Path

__all__ = [
    "APP_NAME",
    "ETC_PATH",
    "LAB_STATIC_CMD_ARGS",
    "MAX_NUMBER_OUTPUTS",
    "PREVIOUS_LOGGING_CHECKSUMS",
    "RUNTIME_ENVIRONMENT_VARIABLES",
    "STARTUP_PATH",
]

APP_NAME = "nublado"
"""Application name, used for logging."""

ETC_PATH = Path("/etc")
"""Configuration directory, usually /etc, but overrideable for tests."""

LAB_STATIC_CMD_ARGS = [
    "jupyterhub-singleuser",
    "--ip=0.0.0.0",
    "--port=8888",
    "--no-browser",
    "--ContentsManager.allow_hidden=True",
    "--FileContentsManager.hide_globs=[]",
    "--KernelSpecManager.ensure_native_kernel=False",
    "--QtExporter.enabled=False",
    "--PDFExporter.enabled=False",
    "--ServerApp.root_dir=/",
    "--WebPDFExporter.enabled=False",
    "--MappingKernelManager.default_kernel_name=lsst",
    "--LabApp.check_for_updates_class=jupyterlab.NeverCheckForUpdate",
]
"""Constants used in Lab startup invocation."""

MAX_NUMBER_OUTPUTS = 10000
"""Maximum number of output lines to display in a Jupyter notebook cell.

Used to prevent OOM-killing if some cell generates a lot of output.
"""

PREVIOUS_LOGGING_CHECKSUMS = [
    "2997fe99eb12846a1b724f0b82b9e5e6acbd1d4c29ceb9c9ae8f1ef5503892ec"
]
"""sha256 sums of previous iterations of ``20-logging.py``.

Used to determine whether upgrading the logging configuration is
needed, or whether the user has made local modifications that
therefore should not be touched.
"""

RUNTIME_ENVIRONMENT_VARIABLES = [
    "ABNORMAL_STARTUP",  # [a]
    "ABNORMAL_STARTUP_ERRNO",  # [a]
    "ABNORMAL_STARTUP_STRERROR",  # [a]
    "ABNORMAL_STARTUP_MESSAGE",  # [a]
    "ABNORMAL_STARTUP_ERRORCODE",  # [a]
    "AWS_SHARED_CREDENTIALS_FILE",  # [b]
    "CONTAINER_SIZE",  # [a]
    "CPU_LIMIT",  # [a]
    "CPU_COUNT",  # [c]
    "DEBUG",  # [a]
    "EXTERNAL_INSTANCE_URL",  # [a]
    "FIREFLY_URL",  # Temporary--can be replaced with JL config variable.
    "GOTO_NUM_THREADS",  # [c]
    "IMAGE_DESCRIPTION",  # [a]
    "IMAGE_DIGEST",  # [a] (maybe obsolete)
    "JUPYTERHUB_ACTIVITY_INTERVAL",  # [d]
    "JUPYTERHUB_ACTIVITY_URL",  # [d]
    "JUPYTERHUB_ADMIN_ACCESS",  # [d]
    "JUPYTERHUB_API_TOKEN",  # [d]
    "JUPYTERHUB_API_URL",  # [d]
    "JUPYTERHUB_BASE_URL",  # [d]
    "JUPYTERHUB_CLIENT_ID",  # [d]
    "JUPYTERHUB_COOKIE_HOST_PREFIX_ENABLED",  # [d]
    "JUPYTERHUB_DEFAULT_URL",  # [d]
    "JUPYTERHUB_HOST",  # [d]
    "JUPYTERHUB_OAUTH_ACCESS_SCOPES",  # [d]
    "JUPYTERHUB_OAUTH_CALLBACK_URL",  # [d]
    "JUPYTERHUB_OAUTH_CLIENT_ALLOWED_SCOPES",  # [d]
    "JUPYTERHUB_OAUTH_SCOPES",  # [d]
    "JUPYTERHUB_PUBLIC_HUB_URL",  # [d]
    "JUPYTERHUB_PUBLIC_URL",  # [a][d]
    "JUPYTERHUB_SERVER_NAME",  # [d]
    "JUPYTERHUB_SERVICE_PREFIX",  # [d]
    "JUPYTERHUB_SERVICE_URL",  # [d]
    "JUPYTERHUB_USER",  # [d]
    "JUPYTERLAB_CONFIG_DIR",  # [d]
    "JUPYTERLAB_START_COMMAND",  # [d]
    "JUPYTER_IMAGE",  # [d] (maybe obsolete)
    "JUPYTER_IMAGE_SPEC",  # [a][d]
    "JUPYTER_PREFER_ENV_PATH",  # [d]
    "JUPYTER_SERVER_ROOT",  # [d]
    "JUPYTER_SERVER_URL",  # [d]: Needed by JupyterHub comms
    "HOME",  # [e]
    "MEM_LIMIT",  # [a]
    "MKL_DOMAIN_NUM_THREADS",  # [c]
    "MPI_NUM_THREADS",  # [c]
    "NUMEXPR_NUM_THREADS",  # [c]
    "NUMEXPR_MAX_THREADS",  # [c]
    "OMP_NUM_THREADS",  # [c]
    "OPENBLAS_NUM_THREADS",  # [c]
    "PANDA_CONFIG_ROOT",  # [b]
    "PGPASSFILE",  # [b]: Possibly r/o mounted secret merged at startup.
    "RAYON_NUM_THREADS",  # [c]: Keep OpenBLAS from getting too excited.
    "RSP_SITE_TYPE",  # Currently used to determine query/tutorial menu.
    "RUNNING_INSIDE_JUPYTERLAB",  # Used by noninteractive
    "USER",  # [e]
    "SCRATCH_DIR",  # Rubin-specific hint for large ephemeral space.
    "TMPDIR",  # [e]: Standard Unix variable for shell and tools.
]
"""Environment variables to be forwarded to the runtime JupyterLab process.

This list is used as a filter; if the named variable is in this list, we
add the name and value to the list of variables ingested for Lab startup.
"""

STARTUP_PATH = Path("/lab_startup")
"""Directory for lab startup files, overrideable for tests.

This will be mounted as an emptyDir by the setup container, and it will have
an environment representation written to it, which will then be consumed by
the Lab startup.
"""
