from enum import auto

from .enums import NubladoEnum

DEFAULT_ADMIN_TOKEN_FILE = "/etc/secret/admin-token"
DEFAULT_CONFIG_FILE = "/usr/local/etc/jupyterhub/existing-secret/values.yaml"

DROPDOWN_SENTINEL_VALUE = "use_image_from_dropdown"


class LabStatus(NubladoEnum):
    STARTING = auto()
    RUNNING = auto()
    TERMINATING = auto()
    FAILED = auto()


class PodState(NubladoEnum):
    PRESENT = auto()
    MISSING = auto()
