# This is taken from jupyterhub/kubespawner
import string

import escapism

safe_chars = set(string.ascii_lowercase + string.digits)


def escape(raw: str) -> str:
    return escapism.escape(raw, safe=safe_chars, excape_char="-").lower()
