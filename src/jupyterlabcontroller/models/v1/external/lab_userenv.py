"""This is also found in the base Config, so must be broken out to avoid
a circular import."""

from typing import Dict, TypeAlias

UserEnv: TypeAlias = Dict[str, str]
"""Environment variables for the spawned Lab.  Both keys and values must
be strings."""
