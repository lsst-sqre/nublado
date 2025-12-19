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
    "--WebPDFExporter.allow_chromium_download=True",
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
    "ABNORMAL_STARTUP",  # [0]
    "ABNORMAL_STARTUP_ERRNO",  # [0]
    "ABNORMAL_STARTUP_STRERROR",  # [0]
    "ABNORMAL_STARTUP_MESSAGE",  # [0]
    "ABNORMAL_STARTUP_ERRORCODE",  # [0]
    "AWS_SHARED_CREDENTIALS_FILE",  # [0]: ABNORMAL_* for error reporting.
    "CPU_LIMIT",  # [1]
    "CPU_COUNT",  # [1]
    "DEBUG",  # Enable debug logging/behavior.
    "FIREFLY_URL",  # Temporary--can be replaced with JL config variable.
    "GOTO_NUM_THREADS",  # [1]
    "JUPYTERHUB_ACTIVITY_INTERVAL",  # [2]
    "JUPYTERHUB_ACTIVITY_URL",  # [2]
    "JUPYTERHUB_ADMIN_ACCESS",  # [2]
    "JUPYTERHUB_API_TOKEN",  # [2]
    "JUPYTERHUB_API_URL",  # [2]
    "JUPYTERHUB_BASE_URL",  # [2]
    "JUPYTERHUB_CLIENT_ID",  # [2]
    "JUPYTERHUB_COOKIE_HOST_PREFIX_ENABLED",  # [2]
    "JUPYTERHUB_DEFAULT_URL",  # [2]
    "JUPYTERHUB_HOST",  # [2]
    "JUPYTERHUB_OAUTH_ACCESS_SCOPES",  # [2]
    "JUPYTERHUB_OAUTH_CALLBACK_URL",  # [2]
    "JUPYTERHUB_OAUTH_CLIENT_ALLOWED_SCOPES",  # [2]
    "JUPYTERHUB_OAUTH_SCOPES",  # [2]
    "JUPYTERHUB_PUBLIC_HUB_URL",  # [2]
    "JUPYTERHUB_PUBLIC_URL",  # [2]
    "JUPYTERHUB_SERVER_NAME",  # [2]
    "JUPYTERHUB_SERVICE_PREFIX",  # [2]
    "JUPYTERHUB_SERVICE_URL",  # [2]
    "JUPYTERHUB_USER",  # [2]
    "JUPYTERLAB_CONFIG_DIR",  # [2]
    "JUPYTERLAB_START_COMMAND",  # [2]
    "JUPYTER_IMAGE",  # [2]
    "JUPYTER_IMAGE_SPEC",  # [2]
    "JUPYTER_PREFER_ENV_PATH",  # [2]
    "JUPYTER_SERVER_ROOT",  # [2]
    "JUPYTER_SERVER_URL",  # [2]: Needed by JupyterHub comms
    "HOME",  # [3]
    "MKL_DOMAIN_NUM_THREADS",  # [1]
    "MPI_NUM_THREADS",  # [1]
    "NUMEXPR_NUM_THREADS",  # [1]
    "NUMEXPR_MAX_THREADS",  # [1]
    "OMP_NUM_THREADS",  # [1]
    "OPENBLAS_NUM_THREADS",  # [1]
    "PANDA_CONFIG_ROOT",  # [0]
    "PGPASSFILE",  # [0]: Possibly r/o mounted secret merged at startup.
    "RAYON_NUM_THREADS",  # [1]: Keep OpenBLAS from getting too excited.
    "RUNNING_INSIDE_JUPYTERLAB",  # Used by noninteractive, possibly obsolete.
    "USER",  # [3]
    "SCRATCH_DIR",  # Rubin-specific hint for large ephemeral space.
    "TMPDIR",  # [3]: Standard Unix variable for shell and tools.
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
