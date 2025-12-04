"""Run a command noninteractively from a configuration JSON file."""

import json
import os
import sys
from pathlib import Path
from typing import Self


class NonInteractiveExecutor:
    """Launch noninteractive Lab container execution from a
    configuration document.
    """

    def __init__(
        self,
        kernel: str,
        command: list[str],
    ) -> None:
        self._kernel = kernel
        self._command = command

    @classmethod
    def from_config(cls, config: Path) -> Self:
        """Load configuration from a JSON document."""
        with config.open() as f:
            obj = json.load(f)
            if obj["type"] != "command":
                raise NotImplementedError(
                    "Only 'command' type noninteractive execution is supported"
                )
            return cls(kernel=obj["kernel"], command=obj["command"])

    def execute(self, env: dict[str, str] | None = None) -> None:
        """Run the command specified in the object, with a supplied
        environment (defaulting to the ambient environment).
        """
        if env is None:
            env = dict(os.environ)
        sys.stdout.flush()
        sys.stderr.flush()
        os.execve(self._command[0], self._command, env=env)
