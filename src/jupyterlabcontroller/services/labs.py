from typing import Dict, List

from fastapi import Depends

from ..dependencies.labs import lab_dependency
from ..models.v1.external.userdata import UserData


def check_for_user(
    username: str, labs: Dict[str, UserData] = Depends(lab_dependency)
) -> bool:
    """True if there's a lab for the user, otherwise false."""
    return username in labs


def get_active_users(
    labs: Dict[str, UserData] = Depends(lab_dependency)
) -> List[str]:
    """Returns a list of users with labs in 'running' state."""
    r: List[str] = []
    for u in labs:
        if labs[u].status == "running":
            r.append(u)
    return r
