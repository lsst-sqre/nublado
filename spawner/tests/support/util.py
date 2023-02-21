"""
Utility functions for testing.
"""


def dashify(item: str) -> str:
    return item.replace("_", "-")


def str_to_bool(inp: str) -> bool:
    """This is OK at detecting False, and everything else is True"""
    inpl = inp.lower()
    if inpl in ("f", "false", "n", "no", "off", "0"):
        return False
    return True
