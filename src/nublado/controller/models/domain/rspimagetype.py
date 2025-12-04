"""RSP Image Types.

This needs to be its own file to avoid circular imports from the filter
policy, but everything but the filter policy can think of it as belonging to
RSPImageTag, from which it is re-exported.
"""

from enum import Enum


class RSPImageType(Enum):
    """The type (generally, release series) of the identified image.

    This is listed in order of priority when constructing menus.  The image
    types listed first will be shown earlier in the menu.
    """

    ALIAS = "Alias"
    RELEASE = "Release"
    WEEKLY = "Weekly"
    DAILY = "Daily"
    CANDIDATE = "Release Candidate"
    EXPERIMENTAL = "Experimental"
    UNKNOWN = "Unknown"
