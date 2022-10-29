from typing import List

from ..models.v1.domains.labs import LabMap


def check_for_user(username: str, labs: LabMap) -> bool:
    """True if there's a lab for the user, otherwise false."""
    return username in labs


def get_active_users(labs: LabMap) -> List[str]:
    """Returns a list of users with labs in 'running' state."""
    r: List[str] = []
    for u in labs:
        if labs[u].status == "running":
            r.append(u)
    return r
