"""Wrapper around executing external commands."""

from __future__ import annotations

import subprocess
from datetime import timedelta
from pathlib import Path
from shlex import join

import structlog

from ..constants import APP_NAME
from ..exceptions import CommandFailedError, CommandTimedOutError

__all__ = ["Command"]


class Command:
    """Wrapper around executing external commands.

    This class provides a generic wrapper around subprocess that is
    helpful for executing external commands, checking their status,
    and optionally capturing their output in a consistent way.

    It represents a slight simplification of the standard ~subprocess.run()
    function. It is intended for use by storage classes that perform
    operations via external commands, which are expected to constrain the
    arguments to the command and the parameters to the run() call.
    """

    def __init__(
        self,
        *,
        capture_output: bool = True,
        ignore_fail: bool = False,
        text: bool = True,
        logger: structlog.BoundLogger | None = None,
    ) -> None:
        """Class to execute commands on behalf of a caller.

        Parameters we do not expect to vary over the caller's lifetime
        are set here, while those that are likely to change
        execution-by-execution are given as arguments to run().

        Parameters
        ----------
        capture_output
            If `True`, collect the process's standard output and standard
            error in the returned object.  If `False`, these streams will
            be inherited from the caller.
        ignore_fail
            If `True`, do not raise an exception on command failure.  If
            the process doesn't run at all, ~subprocess.SubprocessError will
            still be raised.
        text
            If `True`, captured stdout and stderr will be a string rather than
            a bytes sequence.
        """
        if logger is None:
            self._logger = structlog.get_logger(APP_NAME)
        else:
            self._logger = logger
        self._capture_output = capture_output
        self._ignore_fail = ignore_fail
        self._text = text

    def run(
        self,
        *args: str,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout: timedelta | float | None = None,
    ) -> subprocess.CompletedProcess:
        """Run the command with the provided arguments.

        Parameters
        ----------
        *args
            Arguments to the command.  The first argument is the command
            itself, and if not fully-qualified must exist somewhere in the
            caller's `PATH`.
        cwd
            If provided, change working directories to this path before
            running the command.
        env
            If provided, use this dictionary as the process environment.  If
            not, use the caller's process environment.
        timeout
            If given, the command will be terminated and a
            `~lsst.rsp.startup.exceptions.CommandTimedOutError` will be
            raised if execution time exceeds this timeout.

        Raises
        ------
        CommandFailedError
            Raised if the command failed and ``ignore_fail`` was not set to
            `True`.
        CommandTimedOutError
            Raised if ``timeout`` was given and the command took longer than
            that to complete.
        subprocess.SubprocessError
            Raised if the command could not be executed at all.

        """
        check = not self._ignore_fail
        if isinstance(timeout, timedelta):
            timeout = timeout.total_seconds()
        try:
            self._logger.debug(
                f"Running '{join(args)}'",
                cwd=cwd,
                env=env,
                check=check,
                timeout=timeout,
                capture_output=self._capture_output,
                text=self._text,
            )
            result = subprocess.run(
                args,
                cwd=cwd,
                env=env,
                check=check,
                timeout=timeout,
                capture_output=self._capture_output,
                text=self._text,
            )

        except subprocess.CalledProcessError as e:
            raise CommandFailedError(args, e) from e
        except subprocess.TimeoutExpired as e:
            raise CommandTimedOutError(args, e) from e
        if result.returncode != 0:
            self._logger.error(f"Command '{join(args)}' failed", proc=result)
        else:
            self._logger.debug(
                f"Command '{join(args)}' succeeded", proc=result
            )
        return result
