"""RSP Lab preparer."""

import datetime
import json
import os
import shutil
from pathlib import Path
from textwrap import dedent

import structlog
from safir.logging import LogLevel, configure_logging

from ..constants import APP_NAME, LAB_STATIC_CMD_ARGS, STARTUP_PATH
from ..exceptions import RSPErrorCode, RSPStartupError
from .environment import EnvironmentConfigurator
from .homedir import HomedirManager

__all__ = ["Preparer"]


class Preparer:
    """Class to prepare for JupyterLab launch by modifying the filesystem
    and writing out a file representing the runtime environment, to be
    used by the launcher.

    The launcher resides in lsst.rsp.startup; the user Lab should not have
    a copy of the nublado class at all.
    All the launcher does is to read a list of environment variables that
    the preparer writes, sets those, and then starts the JupyterLab process.

    This setup is very Rubin-specific and opinionated, and will
    likely not work for anyone else's science platform.

    If that's you, use this for inspiration, but don't expect this to
    work out of the box.
    """

    def __init__(self) -> None:
        self._broken = False
        self._debug = bool(os.getenv("DEBUG"))
        self._env = {}

        loglevel = LogLevel.DEBUG if self._debug else LogLevel.INFO
        configure_logging(name=APP_NAME, log_level=loglevel)
        self._logger = structlog.get_logger(APP_NAME)

        # We use NUBLADO_HOME here, because we're still running as the
        # provisioner rather than as the end user, who would use HOME. If no
        # home, use /tmp, which should be a shared emptyDir file system with
        # the main container. Abnormal startup will put necessary files there.
        if "NUBLADO_HOME" not in os.environ:
            exc = RSPStartupError(RSPErrorCode.EBADENV, None, "NUBLADO_HOME")
            self._set_abnormal_startup(exc)
            self._home = Path("/tmp")
        else:
            self._home = Path(os.environ["NUBLADO_HOME"])
            # Keep the real homedir for error reporting; HOME will be reset
            # to temporary space (scratch or /tmp) on abnormal startup.
            self._env["NB_HOME"] = str(self._home)

        self._env["HOME"] = str(self._home)

        # Force HOME in our own environment to be the discovered value since
        # git-lfs setup uses HOME.
        os.environ["HOME"] = self._env["HOME"]

    def prepare(self) -> None:
        """Make necessary modifications to start the user lab."""
        # If the user somehow manages to screw up their local environment
        # so badly that JupyterLab won't even start, we will have to
        # bail them out on the fileserver end.  Since JupyterLab is in
        # its own venv, which is not writeable by the user, this should
        # require quite a bit of creativity.
        try:
            self._relocate_user_environment_if_requested()
            if self._home == Path("/tmp"):
                raise RSPStartupError(RSPErrorCode.EBADENV, None, "USER")
            env_mgr = EnvironmentConfigurator(
                env=self._env, logger=self._logger
            )
            self._env = env_mgr.configure_env()
        except OSError as exc:
            self._set_abnormal_startup(exc)

        # Clean up stale cache, check for writeability, try to free some
        # space if necessary.  This stage will manage its own abnormality,
        # since it tries to take some corrective action.
        home_mgr = HomedirManager(
            env=self._env, home=self._home, logger=self._logger
        )
        try:
            home_mgr.tidy_homedir()
        except OSError as exc:
            self._set_abnormal_startup(exc)

        # If everything seems OK so far, copy files into the user's home
        # space and set up git-lfs.
        if not self._broken:
            try:
                home_mgr.copy_files_to_user_homedir()
                home_mgr.modify_interactive_settings()
            except OSError as exc:
                self._set_abnormal_startup(exc)

        # Write the lab startup info out so that the Lab launcher can pick
        # it up.
        #
        # No need to catch this one: if it fails, the lab launcher will not
        # see those files (since they won't be there), and the launcher
        # itself will present the appropriate warning to the user.
        self._write_lab_startup_files()

    def _set_abnormal_startup(self, exc: OSError) -> None:
        """Take an OSError, convert it into an RSPStartupError if necessary,
        and then set the env variables that rsp-jupyter-extensions will use
        to report the error to the user at Lab startup.
        """
        self._broken = True
        if not isinstance(exc, RSPStartupError):
            # This will also catch the EUNKNOWN case
            new_exc = RSPStartupError.from_os_error(exc)
        else:
            new_exc = exc

        self._env["ABNORMAL_STARTUP"] = "TRUE"
        self._env["ABNORMAL_STARTUP_ERRNO"] = str(new_exc.errno)
        self._env["ABNORMAL_STARTUP_STRERROR"] = (
            # Mypy didn't know the above caught the EUNKNOWN case.
            new_exc.strerror
            or os.strerror(int(new_exc.errno or RSPErrorCode.EUNKNOWN.value))
            or f"Unknown error {new_exc.errno}"
        )
        self._env["ABNORMAL_STARTUP_ERRORCODE"] = new_exc.errorcode
        self._env["ABNORMAL_STARTUP_MESSAGE"] = str(new_exc)
        msg = f"Abnormal RSP startup set with exception {new_exc!s}"
        self._logger.error(msg)

    def _clear_abnormal_startup(self) -> None:
        for e in ("", "_ERRNO", "_STRERROR", "_MESSAGE", "_ERRORCODE"):
            del self._env[f"ABNORMAL_STARTUP{e}"]
        self._broken = False
        self._logger.info("Cleared abnormal startup condition")

    def _relocate_user_environment_if_requested(self) -> None:
        if not os.getenv("RESET_USER_ENV"):
            return
        self._logger.debug("User environment relocation requested")
        now = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d%H%M%S")
        reloc = self._home / f".user_env.{now}"
        for candidate in (
            "cache",
            "conda",
            "config",
            "eups",
            "local",
            "jupyter",
        ):
            c_path = self._home / f".{candidate}"
            if c_path.is_dir():
                if not reloc.is_dir():
                    reloc.mkdir()
                tgt = reloc / candidate
                self._logger.debug(f"Moving {c_path.name} to {tgt.name}")
                shutil.move(c_path, tgt)
        u_setups = self._home / "notebooks" / ".user_setups"
        if u_setups.is_file():
            tgt = reloc / "notebooks" / "user_setups"
            tgt.parent.mkdir()
            self._logger.debug(f"Moving {u_setups.name} to {tgt}")
            shutil.move(u_setups, tgt)

    def _make_abnormal_startup_environment(self) -> None:
        # What we're doing is writing (we hope) someplace safe, be that
        # an empty, ephemeral filesystem (such as /tmp in any sanely-configured
        # K8s-based RSP) or in scratch space somewhere.
        #
        # Performance is irrelevant.  As we explain to the user, they should
        # not be using this lab for anything other than immediate problem
        # amelioration.

        # Try a sanity check and ensure that we are in fact in a broken state.
        if not self._broken:
            return

        temphome = self._write_error_report()
        if temphome is None:
            # We cannot proceed: nothing is writeable.
            self._logger.error(
                "Writing files to report abnormal startup failed."
            )
            # Try to persist env and args anyway; we might be able to get as
            # far as displaying a dialog box to the user before exploding.
            self._write_startup_files()

            # The startup container is doomed (so is the Lab).
            raise RSPStartupError(RSPErrorCode.ENOWRITEABLESERVERROOT, None)

        # This is the authoritative choice of temporary home: it is the only
        # directory we know we could actually write the error report into.
        # Do not override it later in startup.
        self._logger.warning(f"Launching with homedir='{temphome}'")
        self._home = temphome
        self._env["HOME"] = str(temphome)

    def _write_error_report(self) -> Path | None:
        """Write the abnormal-startup landing page somewhere writeable.

        Returns
        -------
        Path | None
            The directory the report was written to, which becomes the
            temporary home directory, or `None` if nowhere was writeable.
        """
        txt = self._make_abnormal_landing_markdown()
        s_obj = {"defaultViewers": {"markdown": "Markdown Preview"}}
        s_txt = json.dumps(s_obj)

        # SCRATCH_DIR is set by EnvironmentConfigurator into the Lab
        # environment we are building, not into our own environment, so read
        # it from there.  It will be a user-specific path on a scratch
        # filesystem, and is absent if we never found usable scratch space.
        #
        # Try SCRATCH_DIR first; if it is not writeable (perhaps because it
        # is really on the same volume as /home, as on IDF-dev and -int), fall
        # back to /tmp.  Any reasonably-configured RSP running under K8s will
        # not have a shared /tmp.  If neither is writeable, give up and return
        # None.  Use dict.fromkeys(), rather than a set, so that the order is
        # deterministic when SCRATCH_DIR is set.
        th = self._env.get("SCRATCH_DIR", "/tmp")
        ths = [Path(x) for x in dict.fromkeys((th, "/tmp"))]
        for attempt, temphome in enumerate(ths, start=1):
            welcome = temphome / "notebooks" / "tutorials" / "welcome.md"
            try:
                welcome.parent.mkdir(exist_ok=True, parents=True)
                welcome.write_text(txt)
                settings = (
                    temphome
                    / ".jupyter"
                    / "lab"
                    / "user-settings"
                    / "@jupyterlab"
                    / "docmanager-extension"
                    / "plugin.jupyterlab-settings"
                )
                settings.parent.mkdir(exist_ok=True, parents=True)
                settings.write_text(s_txt)
                return temphome
            except Exception as exc:
                # Only the final failure is fatal; log the rest as warnings so
                # a successful fallback does not look like an error.
                if attempt < len(ths):
                    self._logger.warning(
                        f"Writing abnormal startup report to {temphome!s}"
                        f" failed ({exc!s}); trying next candidate"
                    )
                else:
                    self._logger.exception(
                        f"Writing abnormal startup report to {temphome!s}"
                        " failed"
                    )
        # If we got here, we couldn't write.
        return None

    def _make_abnormal_landing_markdown(self) -> str:
        errmsg = self._env.get("ABNORMAL_STARTUP_MESSAGE", "<no message>")
        errcode = self._env.get("ABNORMAL_STARTUP_ERRORCODE", "EUNKNOWN")

        self._logger.error(
            f"Abnormal startup: errorcode {errcode}; message {errmsg}"
        )

        open_an_issue = dedent(
            f"""

            Please open an issue with your RSP site administrator with the
            following information: `{errmsg}`
            """
        )

        # Start with generic error text.  It's very simple markdown, with a
        # heading and literal text only.

        txt = dedent("""
        # Abnormal startup

        Your Lab container did not start normally.

        Do not trust this lab for work you want to keep.

        """)

        # Now add error-specific advice.
        match errcode:
            case "EDQUOT":
                txt += dedent(
                    f"""
                    You have exceeded your quota.  Try using the terminal to
                    remove unneeded files in `{self._home!s}`.  You can use the
                    `quota` command to check your usage.

                    After that, shut down and restart the lab.  If that does
                    not result in a working lab:
                    """
                )
            case "ENOSPC":
                txt += dedent(
                    f"""
                    You have run out of filesystem space.  Try using the
                    terminal to remove unneeded files in `{self._home!s}`.
                    Since the filesystem is full, this may not be something
                    you can correct.

                    After you have trimmed whatever possible, shut down and
                    restart the lab.

                    If that does not result in a working lab:
                    """
                )
            case "EROFS" | "EACCES":
                txt += dedent(
                    """
                    You do not have permission to write.  Ask your RSP
                    administrator to check ownership and permissions on your
                    directories.
                    """
                )
            case "EBADENV":
                txt += dedent(
                    """
                    You are missing environment variables necessary for RSP
                    operation.
                    """
                )
            case _:
                pass
        txt += dedent(open_an_issue)
        return txt

    def _set_timeout_variables(self) -> list[str]:
        timeout_map = {
            "NO_ACTIVITY_TIMEOUT": "ServerApp.shutdown_no_activity_timeout",
            "CULL_KERNEL_IDLE_TIMEOUT": (
                "MappingKernelManager.cull_idle_timeout"
            ),
            "CULL_KERNEL_CONNECTED": "MappingKernelManager.cull_connected",
            "CULL_KERNEL_INTERVAL": "MappingKernelManager.cull_interval",
            "CULL_TERMINAL_INACTIVE_TIMEOUT": (
                "TerminalManager.cull_inactive_timeout"
            ),
            "CULL_TERMINAL_INTERVAL": "TerminalManager.cull_interval",
        }
        result: list[str] = []
        for envvar, setting in timeout_map.items():
            if val := os.getenv(envvar):
                result.append(f"--{setting}={val}")
        return result

    def _write_lab_startup_files(self) -> None:
        # Used by shell startup inside sciplat-lab (Rubin-specific).  Set
        # before the abnormal startup handling, because that may write the
        # startup files itself and then bail out.
        self._env["RUNNING_INSIDE_JUPYTERLAB"] = "TRUE"

        if self._broken:
            self._logger.warning(
                f"Abnormal startup: {self._env['ABNORMAL_STARTUP_MESSAGE']}"
            )
            # This resets HOME and self._home to wherever it managed to write
            # the error report, so that the Lab's notebook-dir is a directory
            # the user can actually see the report in.
            self._make_abnormal_startup_environment()

        self._write_startup_files()

    def _write_startup_files(self) -> None:
        # If any of these fails, lsst.rsp.startup ought to react to the
        # lack of the appropriate files and start in degraded mode with
        # an explanation.
        try:
            self._write_lab_environment()
            self._write_lab_args()
        except Exception:
            self._logger.exception("Writing Lab startup files failed")

    def _write_lab_environment(self) -> None:
        env_file = STARTUP_PATH / "env.json"
        env_file.write_text(json.dumps(self._env, indent=2, sort_keys=True))

    def _write_lab_args(self) -> None:
        log_level = "DEBUG" if self._debug else "INFO"
        cmd_args = list(LAB_STATIC_CMD_ARGS)
        cmd_args.append(f"--notebook-dir={self._home!s}")
        cmd_args.append(f"--log-level={log_level}")
        cmd_args.extend(self._set_timeout_variables())
        args_file = STARTUP_PATH / "args.json"
        args_file.write_text(json.dumps(cmd_args, indent=2))
