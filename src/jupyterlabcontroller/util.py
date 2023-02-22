"""General utility functions."""


def deslashify(data: str) -> str:
    return data.replace("/", "_._")


def str_to_bool(inp: str) -> bool:
    """This is OK at detecting False, and everything else is True"""
    inpl = inp.lower()
    if inpl in ("f", "false", "n", "no", "off", "0"):
        return False
    return True
