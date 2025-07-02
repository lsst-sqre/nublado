"""Model for purger policy."""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, TypeAlias

from pydantic import BeforeValidator, Field
from safir.pydantic import CamelCaseModel, HumanTimedelta

# HumanSizeBytes should eventually go into safir.pydantic next to
# HumanTimedelta.


@dataclass
class MantissaAndMultiplier:
    """Utility for intermediate results in HumanSizeBytes conversion."""

    mantissa: str
    multiplier: float


def _validate_human_size_bytes(v: str | float) -> int:
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        if int(v) == v:
            return int(v)
        raise ValueError("Could not convert {v} to integer")
    orig_v = v
    v = v.strip()  # remove leading/trailing whitespace
    if v.endswith(("B", "b")):  # "b" is incorrect but common.
        v = v[:-1]
        v = v.strip()  # In case it was something like '42 B'
    try:
        return int(v)  # Maybe it's just a stringified int?
    except ValueError:
        pass  # Nope, try to convert it.
    mam = _extract_base_and_mult_from_string(v)
    try:
        n_v = float(mam.mantissa)
        m_v = n_v * mam.multiplier
        # Cheating: we will just round nearest if mult is not a power of 10.
        if mam.multiplier % 10 != 0:
            m_v = int(m_v + 0.5)
        if m_v != int(m_v):
            # Otherwise we complain that it's not an integer, to catch
            # Way Too Much Precision (e.g. "1.234567 KiB")
            raise ValueError  # Caught immediately and reraised with text.
        return int(m_v)
    except ValueError:
        raise ValueError(f"Could not convert '{orig_v}' to integer") from None


def _extract_base_and_mult_from_string(v: str) -> MantissaAndMultiplier:
    mult = 1.0  # The things in the map turn out to be floats.
    # Since we require Python 3.12, this dict is ordered as shown.
    mult_map = {
        "k": 1e3,
        "K": 1e3,  # technically incorrect, but common
        "M": 1e6,
        "G": 1e9,
        "T": 1e12,
        "P": 1e15,
        "E": 1e18,
        "ki": 2**10,
        "Ki": 2**10,  # also incorrect.
        "Mi": 2**20,
        "Gi": 2**30,
        "Ti": 2**40,
        "Pi": 2**50,
        "Ei": 2**60,
    }
    suffixes = list(mult_map.keys())
    for s in suffixes:
        if v.endswith(s):
            v = v[: -len(s)]
            mult = mult_map[s]
            break
    v = v.strip()
    return MantissaAndMultiplier(mantissa=v, multiplier=mult)


HumanSizeBytes: TypeAlias = Annotated[
    int, BeforeValidator(_validate_human_size_bytes)
]
"""Parse an input indicating a number of bytes into an int.

The general use-case is to represent a value such as '2.37 MB' as an
integer.

Accepts as input an integer, a float that happens to be an integer
(that is, 32.0 is a legal input) or a string.  A non-integral float
will raise a ValueError.  If the input is an integer or an integral
float, the integer corresponding to the input is returned.

That leaves the string case.  If the final character of the string is
"B" or (incorrectly, since "b" should mean bits rather than bytes)
"b", first that character is removed.  Then the remaining suffix is
interpreted as a multiplier, as follows:

- "k" (or, incorrectly, "K"):   1000
- "M":                          1_000_000
- "G":                          1_000_000_000
- "T":                          1_000_000_000_000
- "P":                          1_000_000_000_000_000
- "E":                          1_000_000_000_000_000_000
- "ki" (or, incorrectly, "Ki"): 2 ** 10
- "Mi":                         2 ** 20
- "Gi":                         2 ** 30
- "Ti":                         2 ** 40
- "Pi":                         2 ** 50
- "Ei":                         2 ** 60

The part of the string, with leading and trailing whitespace ignored, is
treated as a number if possible, and is multiplied by the multiplier (if any).

If the resulting number is an integer, that integer is returned.  Otherwise
a ValueError is raised indicating the string could not be converted.
"""


class Intervals(CamelCaseModel):
    """Intervals specify how long it must have been since a filesystem object
    was accessed, created, or modified before that object will be considered
    for purging.  A value of None (or a zero TimeDelta) means the object will
    not be considered for purging on the given grounds.
    """

    access_interval: Annotated[
        HumanTimedelta | None,
        Field(title="Maximum time since last file access"),
    ] = None

    creation_interval: Annotated[
        HumanTimedelta | None, Field(title="Maximum time since file creation")
    ] = None

    modification_interval: Annotated[
        HumanTimedelta | None,
        Field(title="Maximum time since file modification"),
    ] = None

    def to_dict(self) -> dict[str, int]:
        ret: dict[str, int] = {
            "access_interval": 0,
            "creation_interval": 0,
            "modification_interval": 0,
        }
        if self.access_interval is not None:
            ret["access_interval"] = int(self.access_interval.total_seconds())
        if self.creation_interval is not None:
            ret["creation_interval"] = int(
                self.creation_interval.total_seconds()
            )
        if self.modification_interval is not None:
            ret["modification_interval"] = int(
                self.modification_interval.total_seconds()
            )
        return ret


class SizedIntervals(CamelCaseModel):
    """Container to hold intervals for purging `large` and `small` files."""

    large: Annotated[
        Intervals, Field(title="Intervals before purging large files")
    ] = Intervals()

    small: Annotated[
        Intervals, Field(title="Intervals before purging small files")
    ] = Intervals()

    def to_dict(self) -> dict[str, dict[str, int]]:
        return {"large": self.large.to_dict(), "small": self.small.to_dict()}


class DirectoryPolicy(CamelCaseModel):
    """Policy for purging objects from a directory and its children."""

    path: Annotated[Path, Field(title="Directory to consider for purging")]

    threshold: Annotated[
        HumanSizeBytes,
        Field(title="Size in bytes demarcating `large` from `small` files"),
    ]

    intervals: Annotated[
        SizedIntervals,
        Field(title="Intervals before purging `large` and `small` files"),
    ]

    def to_dict(self) -> dict[str, str | int | dict[str, dict[str, int]]]:
        return {
            "path": str(self.path),
            "threshold": self.threshold,
            "intervals": self.intervals.to_dict(),
        }


class Policy(CamelCaseModel):
    """Policy for purging objects across multiple directory trees."""

    directories: Annotated[
        list[DirectoryPolicy],
        Field(title="Directories specified in this policy"),
    ]

    def get_directories(self) -> list[Path]:
        """Return list of directories specified in this policy, sorted by
        length, shortest first.

        The sort order is important so that we can start with most-specific
        and work our way to least-specific.  This is also the way
        ingress-nginx sorts its ingresses, and it seems to work fine there.

        When traversing the list, we just pop() off the end and work our way
        back.
        """
        return sorted(
            [x.path for x in self.directories], key=lambda x: len(str(x))
        )

    def to_dict(
        self,
    ) -> dict[str, list[dict[str, str | int | dict[str, dict[str, int]]]]]:
        return {"directories": [x.to_dict() for x in self.directories]}
