from enum import auto

from .enums import NubladoEnum

DEFAULT_ADMIN_TOKEN_FILE = "/etc/secret/admin-token"
DEFAULT_CONFIG_FILE = "/usr/local/etc/jupyterhub/existing-secret/values.yaml"


class LabStatus(NubladoEnum):
    STARTING = auto()
    RUNNING = auto()
    TERMINATING = auto()
    FAILED = auto()
