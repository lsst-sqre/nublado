"""Constants for RSP startup."""

from pathlib import Path

__all__ = [
    "APP_NAME",
    "ETC_PATH",
    "LAB_STATIC_CMD_ARGS",
    "MAX_NUMBER_OUTPUTS",
    "PREVIOUS_LOGGING_CHECKSUMS",
    "STARTUP_PATH",
]

APP_NAME = "nublado"
"""Application name, used for logging."""


CONFIG_FILE = Path("/etc/nublado/config/lab-config.json")
"""Lab config file, overrideable for tests.

Usually /etc/nublado/config/lab_config.json.
"""

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

STARTUP_PATH = Path("/etc/nublado/startup")
"""Directory for lab startup files, overrideable for tests.

This will be mounted as an emptyDir by the setup container, and it will have
an environment representation written to it, which will then be consumed by
the Lab startup.
"""
