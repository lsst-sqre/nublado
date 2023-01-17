"""General utility functions."""

import os
from typing import Any, Dict

import yaml

_config: Dict[str, Any] = {}


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


def get_namespace() -> str:
    ns_path = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
    if os.path.exists(ns_path):
        with open(ns_path) as f:
            ns = f.read().strip()
    else:
        ns = "userlabs"
    return ns


def _get_config() -> Dict[str, Any]:
    global _config
    if not _config:
        config_path = "/usr/local/etc/jupyterhub/existing-secret/values.yaml"
        if os.path.exists(config_path):
            with open(config_path) as f:
                _config = yaml.safe_load(f)
    return _config


def get_external_instance_url() -> str:
    cfg = _get_config()
    try:
        ext_url = cfg["global"]["baseUrl"]
    except KeyError:
        ext_url = os.getenv("EXTERNAL_INSTANCE_URL", "http://localhost:8080/")
    return ext_url


def get_hub_base_url() -> str:
    cfg = _get_config()
    try:
        hub_base = cfg["hub"]["baseUrl"]
    except KeyError:
        hub_base = "/hub"
    return hub_base
