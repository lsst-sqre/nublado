"""Automatic enums where the enum name is all-caps but the value is lowercase.
"""
from enum import Enum


class NubladoEnum(str, Enum):
    """This will validate that the name is entirely upper case, and
    will produce auto() values in lower case.  This is exactly StrEnum from
    Python 3.11, except for the validation step."""

    def _generate_next_value_(  # type: ignore
        name, start, count, last_values
    ) -> str:
        if name != name.upper():
            raise RuntimeError("Enum names must be entirely upper-case")
        return name.lower()
