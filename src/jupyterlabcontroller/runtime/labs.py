from typing import Dict

from ..models.userdata import UserData

"""The 'users' dict holds a mapping of user name to a UserData struct;
status is updated during creation and deletion.  Upon successful deletion,
the user entry is removed.
"""
users: Dict[str, UserData] = {}
