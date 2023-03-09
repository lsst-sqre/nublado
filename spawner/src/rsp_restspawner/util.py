"""General utility functions."""

import os
from typing import Any, Dict

import yaml

from .constants import DEFAULT_ADMIN_TOKEN_FILE, DEFAULT_CONFIG_FILE


def to_camel_case(string: str) -> str:
    """Convert a string to camel case.

    Originally written for use with Pydantic as an alias generator so that the
    model can be initialized from camel-case input (such as Kubernetes
    objects).

    Parameters
    ----------
    string
        Input string

    Returns
    -------
    str
        String converted to camel-case with the first character in lowercase.
    """
    components = string.split("_")
    return components[0] + "".join(c.title() for c in components[1:])


def get_config() -> Dict[str, Any]:
    """Returns the configuration YAML, read from a file (usually mounted as
    a configmap) parsed into a Python dict."""
    config_file = os.getenv("RESTSPAWNER_CONFIG_FILE", DEFAULT_CONFIG_FILE)
    with open(config_file) as f:
        return yaml.safe_load(f)


def get_admin_token() -> str:
    """Returns the admin token, read from a file (usually mounted as a
    secret)."""
    token_file = os.getenv(
        "RESTSPAWNER_ADMIN_TOKEN_FILE", DEFAULT_ADMIN_TOKEN_FILE
    )
    with open(token_file, "r") as f:
        return f.read().strip()


def get_external_instance_url() -> str:
    cfg = get_config()
    try:
        ext_url = cfg["global"]["baseUrl"]
    except KeyError:
        ext_url = os.getenv("EXTERNAL_INSTANCE_URL", "http://localhost:8080/")
    return ext_url


def get_hub_base_url() -> str:
    cfg = get_config()
    try:
        hub_base = cfg["hub"]["baseUrl"]
    except KeyError:
        hub_base = "/hub"
    return hub_base
