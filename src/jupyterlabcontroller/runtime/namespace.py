import os


def get_namespace_prefix() -> str:
    """To identify namespaces: the user namespace will be the namespace
    prefix, then a dash, then the (escaped) username.

    If USER_NAMESPACE_PREFIX is set in the environment, that will be used as
    the namespace prefix.  If it is not, the namespace will be read from the
    container.  If that file does not exist, "userlabs" will be used.
    """
    r: str = os.getenv("USER_NAMESPACE_PREFIX", "")
    if r:
        return r
    ns_path = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
    if os.path.exists(ns_path):
        with open(ns_path) as f:
            return f.read().strip()
    return "userlabs"
