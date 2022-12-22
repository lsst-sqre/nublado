import os
from typing import Optional

_admin_token: Optional[str] = None
_TOKEN_FILE = "/etc/secret/admin-token"


def get_admin_token() -> str:
    global _admin_token
    if _admin_token is None:
        _admin_token = os.getenv("ADMIN_TOKEN")
        if _admin_token is None:
            with open(_TOKEN_FILE, "r") as f:
                _admin_token = f.read().strip()
    return _admin_token
