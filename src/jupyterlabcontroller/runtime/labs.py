from typing import Dict, List

from ..models.v1.external.userdata import UserData

"""The 'users' dict holds a mapping of user name to a UserData struct;
status is updated during creation and deletion.  Upon successful deletion,
the user entry is removed.
"""
labs: Dict[str, UserData] = {}


def check_for_user(username: str) -> bool:
    """True if there's a lab for the user, otherwise false."""
    return username in labs


def get_active_users() -> List[str]:
    """Returns a list of users with labs in 'running' state."""
    r: List[str] = []
    for u in labs:
        if labs[u].status == "running":
            r.append(u)
    return r
