"""Constants for jupyterlab-controller
"""

CONFIGURATION_PATH = "/etc/nublado/config.yaml"
DOCKER_SECRETS_PATH = "/etc/secrets/.dockerconfigjson"

ADMIN_SCOPE = "admin:jupyterlab"
USER_SCOPE = "exec:notebook"

KUBERNETES_API_TIMEOUT: int = 60
