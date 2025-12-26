"""RSP Lab preparer."""

import asyncio
import configparser
import contextlib
import datetime
import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from textwrap import dedent
from typing import Any
from urllib.parse import parse_qsl, urlparse

import structlog
import yaml
from rubin.repertoire import DiscoveryClient, RepertoireError
from safir.logging import LogLevel, configure_logging

from ..constants import (
    APP_NAME,
    ETC_PATH,
    LAB_STATIC_CMD_ARGS,
    MAX_NUMBER_OUTPUTS,
    PREVIOUS_LOGGING_CHECKSUMS,
    RUNTIME_ENVIRONMENT_VARIABLES,
    STARTUP_PATH,
)
from ..exceptions import RSPErrorCode, RSPStartupError
from ..storage.command import Command
from ..utils import (
    get_access_token,
    get_digest,
    get_jupyterlab_config_dir,
    get_runtime_mounts_dir,
)

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
        # We start with a copy of our own environment.
        # Only a subset of this will be forwarded into the launch
        # environment; most of it will be used for internal housekeeping
        # during the setup process.
        self._env = os.environ.copy()
        self._debug = bool(self._env.get("DEBUG", ""))
        loglevel = LogLevel.DEBUG if self._debug else LogLevel.INFO
        configure_logging(name=APP_NAME, log_level=loglevel)
        self._logger = structlog.get_logger(APP_NAME)
        self._broken = False
        for req_env in ("JUPYTERHUB_BASE_URL", "NUBLADO_HOME"):
            if req_env not in self._env:
                exc = RSPStartupError("EBADENV", None, req_env)
                self._set_abnormal_startup(exc)
        # We use NUBLADO_HOME here, because we're still running as the
        # provisioner rather than as the end user, who would use HOME
        #
        # However, we also force HOME to be our new value, because the
        # git LFS setup we run uses HOME.  Of course, that won't persist
        # beyond this process.
        #
        # If no home, use /tmp?  It won't work but at least if we create
        # stuff there it will be harmless, and the user will get a message
        # indicating what's wrong.
        self._home = Path(self._env.get("NUBLADO_HOME", "/tmp"))
        self._env["HOME"] = f"{self._home!s}"
        os.environ["HOME"] = self._env["HOME"]
        if self._env["HOME"] == "/tmp":
            self._env["USER"] = "@@@user_unknown@@@"
        else:
            self._env["USER"] = self._home.name  # Last component of homedir
        self._cmd = Command(ignore_fail=True, logger=self._logger)
        self._ext_url = self._env.get(
            "EXTERNAL_INSTANCE_URL", "https://localhost:8888"
        )
        rep_url = self._env.get(
            "REPERTOIRE_BASE_URL", self._ext_url + "/repertoire"
        )
        self._discovery = DiscoveryClient(base_url=rep_url)

    def prepare(self) -> None:
        """Make necessary modifications to start the user lab."""
        # If the user somehow manages to screw up their local environment
        # so badly that JupyterLab won't even start, we will have to
        # bail them out on the fileserver end.  Since JupyterLab is in
        # its own venv, which is not writeable by the user, this should
        # require quite a bit of creativity.
        try:
            self._relocate_user_environment_if_requested()
            self._configure_env()
        except OSError as exc:
            self._set_abnormal_startup(exc)

        # Clean up stale cache, check for writeability, try to free some
        # space if necessary.  This stage will manage its own abnormality,
        # since it tries to take some corrective action.
        self._tidy_homedir()

        # If everything seems OK so far, copy files into the user's home
        # space and set up git-lfs.

        if not self._broken:
            try:
                self._copy_files_to_user_homedir()
                self._setup_git()
            except OSError as exc:
                self._set_abnormal_startup(exc)

        if not bool(self._env.get("NONINTERACTIVE", "")):
            self._modify_interactive_settings()

        # Write the lab startup info out so that the Lab launcher can pick
        # it up.
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
        if not self._env.get("RESET_USER_ENV", ""):
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
        # Now that we've done that, clear the environment reset flag.
        del self._env["RESET_USER_ENV"]

    #
    # Next up, a big block of setting up our subprocess environment.
    # Most of this stuff does end up in the runtime environment.
    #
    def _configure_env(self) -> None:
        self._logger.debug("Configuring environment for JupyterLab process")
        self._set_user()
        self._set_tmpdir_if_scratch_available()
        self._set_butler_cache()
        self._set_cpu_variables()
        self._set_image_digest()
        self._expand_panda_tilde()
        asyncio.run(self._set_firefly_variables())
        self._force_jupyter_prefer_env_path_false()
        self._set_butler_credential_variables()
        self._logger.debug("Lab process environment", env=self._env)

    def _set_user(self) -> None:
        self._logger.debug("Determining user name")
        # If we're starting in /tmp, we couldn't figure out the user name,
        # so we have to give up.
        if self._home == Path("/tmp"):
            raise RSPStartupError(RSPErrorCode.EBADENV, None, "USER")
        user = self._home.name
        # We will propagate this forward.
        self._env["USER"] = user

    def _check_user_scratch_subdir(self, path: Path) -> Path | None:
        # This is very Rubin specific.  We generally have a large
        # world-writable filesystem in a scratch path.
        #
        # Given a path we will test that SCRATCH_PATH/user/path can be
        # created as a writable directory (or that it already exists
        # as a writable directory).  If it can be (or is), we return the
        # whole path, and if not, we return None.  If we can set it,
        # we also set the SCRATCH_DIR environment variable to point to it.
        #
        # This will only be readable by the user; they can chmod() it if
        # they want to share, but for TMPDIR and DAF_BUTLER_CACHE_DIRECTORY
        # they probably should not.  The mode will not be reset if the
        # directory already exists and is writeable

        scratch_path = Path(os.getenv("SCRATCH_PATH") or "/scratch")

        if not scratch_path.is_dir():
            self._logger.debug(
                # Debug only: not having /scratch is reasonable.
                f"{scratch_path} is not a directory."
            )
            return None
        # The username will be the last component of NUBLADO_HOME
        user = self._env.get("USER", "")
        if not user:
            self._logger.warning("Could not determine user from environment")
            return None
        schema = self._env.get("HOMEDIR_SCHEMA", "username")
        user_scratch_dir = scratch_path / user
        # This is pretty ad-hoc, but USDF uses the first letter in the
        # username for both home and scratch
        if schema == "initialThenUsername":
            user_scratch_dir = scratch_path / user[0] / user
        user_scratch_path = user_scratch_dir / path
        try:
            user_scratch_path.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError as exc:
            self._logger.warning(
                f"Could not create directory at {user_scratch_path!s}: {exc}"
            )
            return None
        if not os.access(user_scratch_path, os.W_OK):
            self._logger.warning(f"Unable to write to {user_scratch_path!s}")
            return None
        self._logger.debug(f"Using user scratch path {user_scratch_path!s}")
        # Set user-specific top dir as SCRATCH_DIR
        self._env["SCRATCH_DIR"] = f"{user_scratch_dir!s}"
        return user_scratch_path

    def _set_tmpdir_if_scratch_available(self) -> None:
        # Assuming that TMPDIR is not already set (e.g. by the spawner),
        # we will try to create <scratch_path>/<user>/tmp and ensure it is a
        # writeable directory, and if it is, TMPDIR will be repointed to it.
        # This will then reduce our ephemeral storage issues, which have
        # caused mass pod eviction and destruction of the prepull cache.
        #
        # In our tests at the IDF, on a 2CPU/8GiB "Medium", TMPDIR on
        # /scratch (NFS) is about 15% slower than on local ephemeral storage.
        self._logger.debug("Resetting TMPDIR if scratch storage available")
        tmpdir = self._env.get("TMPDIR", "")
        if tmpdir:
            self._logger.debug(f"Not setting TMPDIR: already set to {tmpdir}")
            return
        temp_path = self._check_user_scratch_subdir(Path("tmp"))
        if temp_path:
            self._env["TMPDIR"] = str(temp_path)
            self._logger.debug(f"Set TMPDIR to {temp_path!s}")
        else:
            self._logger.debug("Did not set TMPDIR")

    def _set_butler_cache(self) -> None:
        # This is basically the same story as TMPDIR.
        env_v = "DAF_BUTLER_CACHE_DIRECTORY"
        dbcd = self._env.get(env_v, "")
        if dbcd:
            self._logger.debug(f"Not setting {env_v}: already set to {dbcd}")
            return
        temp_path = self._check_user_scratch_subdir(Path("butler_cache"))
        if temp_path:
            self._env[env_v] = str(temp_path)
            self._logger.debug(f"Set {env_v} to {temp_path!s}")
            return
        # In any sane RSP environment, /tmp will not be shared (it will
        # be either tmpfs or on ephemeral storage, and in any case not
        # visible beyond its own pod), so we are not actually using a risky
        # shared directory.
        self._env[env_v] = "/tmp/butler_cache"

    def _set_cpu_variables(self) -> None:
        self._logger.debug("Setting CPU threading variables")
        try:
            cpu_limit = int(float(self._env.get("CPU_LIMIT", "1")))
        except ValueError:
            cpu_limit = 1
        cpu_limit = max(cpu_limit, 1)
        cpu_limit_str = str(cpu_limit)
        for vname in (
            "CPU_LIMIT",
            "CPU_COUNT",
            "GOTO_NUM_THREADS",
            "MKL_DOMAIN_NUM_THREADS",
            "MPI_NUM_THREADS",
            "NUMEXPR_NUM_THREADS",
            "NUMEXPR_MAX_THREADS",
            "OMP_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "RAYON_NUM_THREADS",
        ):
            self._env[vname] = cpu_limit_str
            self._logger.debug(f"Set '{vname}' -> '{cpu_limit_str}'")

    def _set_image_digest(self) -> None:
        self._logger.debug("Setting image digest if available")
        # get_digest() is already a helper function in our parent package.
        digest = get_digest()
        if digest:
            self._logger.debug(f"Set image digest to '{digest}'")
            self._env["IMAGE_DIGEST"] = digest
        else:
            self._logger.debug("Could not get image digest")

    def _expand_panda_tilde(self) -> None:
        self._logger.debug("Expanding tilde in PANDA_CONFIG_ROOT, if needed")
        if "PANDA_CONFIG_ROOT" in self._env:
            # We've already been through set_user(), so USER must be set.
            username = self._env["USER"]
            path = Path(self._env["PANDA_CONFIG_ROOT"])
            path_parts = path.parts
            if path_parts[0] in ("~", f"~{username}"):
                new_path = Path(self._home, *path_parts[1:])
                self._logger.debug(
                    f"Replacing PANDA_CONFIG_ROOT '{path!s}'"
                    f"with '{new_path!s}'"
                )
                self._env["PANDA_CONFIG_ROOT"] = str(new_path)
            elif path_parts[0].startswith("~"):
                self._logger.warning(f"Cannot expand tilde in '{path!s}'")

    async def _set_firefly_variables(self) -> None:
        self._logger.debug("Setting firefly variables")
        emsg = "Discovery of portal service failed; not setting variables"
        try:
            ff_url = await self._discovery.url_for_ui("portal")
        except RepertoireError:
            self._logger.exception(emsg)
            return
        finally:
            await self._discovery.aclose()  # Done with discovery client.
        if not ff_url:
            self._logger.warning(emsg)
            return
        self._env["FIREFLY_URL"] = ff_url
        self._logger.debug(f"Firefly URL -> '{ff_url}'")

    def _force_jupyter_prefer_env_path_false(self) -> None:
        # cf https://discourse.jupyter.org/t/jupyter-paths-priority-order/7771
        # and https://jupyter-core.readthedocs.io/en/latest/changelog.html#id63
        #
        # As long as we're running from the stack Python, we need to ensure
        # this is turned off.
        self._logger.debug("Forcing JUPYTER_PREFER_ENV_PATH to 'no'")
        self._env["JUPYTER_PREFER_ENV_PATH"] = "no"

    def _set_butler_credential_variables(self) -> None:
        # We split this up into environment manipulation and later
        # file substitution.  This is the environment part.
        self._logger.debug("Setting Butler credential variables")
        cred_dir = self._home / ".lsst"
        if "AWS_SHARED_CREDENTIALS_FILE" in self._env:
            awsname = Path(self._env["AWS_SHARED_CREDENTIALS_FILE"]).name
            self._env["ORIG_AWS_SHARED_CREDENTIALS_FILE"] = self._env[
                "AWS_SHARED_CREDENTIALS_FILE"
            ]
            newaws = str(cred_dir / awsname)
            self._env["AWS_SHARED_CREDENTIALS_FILE"] = newaws
            self._logger.debug(
                f"Set 'AWS_SHARED_CREDENTIALS_FILE' -> '{newaws}'"
            )
        if "PGPASSFILE" in self._env:
            pgpname = Path(self._env["PGPASSFILE"]).name
            newpg = str(cred_dir / pgpname)
            self._env["ORIG_PGPASSFILE"] = self._env["PGPASSFILE"]
            self._env["PGPASSFILE"] = newpg
            self._logger.debug(f"Set 'PGPASSFILE' -> '{newpg}'")

    #
    # The second big block tries to tidy the home directory.
    #
    def _tidy_homedir(self) -> None:
        self._clean_astropy_cache()
        self._test_for_space()

    def _clean_astropy_cache(self) -> None:
        # This is extremely conservative.  We only find URLs with an
        # "Expires" parameter (in practice, s3 signed URLs), and remove
        # the key and contents if the expiration is in the past.
        cachedir = self._home / ".astropy" / "cache" / "download" / "url"
        if not cachedir.exists():
            return
        candidates = [x for x in cachedir.iterdir() if x.is_dir()]
        for c in candidates:
            urlfile = c / "url"
            if not urlfile.is_file():
                continue
            try:
                url = urlfile.read_text()
            except Exception:
                self._logger.exception("Could not read {urlfile!s}")
                continue
            qry = urlparse(url).query
            if not qry:
                continue
            for key, value in parse_qsl(qry):
                if key.lower() == "expires":
                    self._handle_expiry(c, value)

    def _modify_interactive_settings(self) -> None:
        self._logger.debug("Modifying interactive settings if needed")
        # These both write files; if either fails, start up but warn
        # the user their experience is likely to be bad.
        try:
            self._manage_access_token()
            self._increase_log_limit()
        except OSError as exc:
            self._set_abnormal_startup(exc)

    def _increase_log_limit(self) -> None:
        self._logger.debug("Increasing log limit if needed")
        settings: dict[str, Any] = {}
        settings_dir = (
            self._home
            / ".jupyter"
            / "lab"
            / "user-settings"
            / "@jupyterlab"
            / "notebook-extension"
        )
        settings_dir.mkdir(parents=True, exist_ok=True)
        settings_file = settings_dir / "tracker.jupyterlab.settings"
        if settings_file.is_file():
            with settings_file.open() as f:
                settings = json.load(f)
        current_limit = settings.get("maxNumberOutputs", 0)
        if current_limit < MAX_NUMBER_OUTPUTS:
            self._logger.warning(
                f"Changing maxNumberOutputs in {settings_file!s}"
                f" from {current_limit} to {MAX_NUMBER_OUTPUTS}"
            )
            settings["maxNumberOutputs"] = MAX_NUMBER_OUTPUTS
            with settings_file.open("w") as f:
                json.dump(settings, f, sort_keys=True, indent=4)
        else:
            self._logger.debug("Log limit increase not needed")

    def _manage_access_token(self) -> None:
        self._logger.debug("Updating access token")
        tokfile = self._home / ".access_token"
        tokfile.unlink(missing_ok=True)
        ctr_token = get_runtime_mounts_dir() / "secrets" / "token"
        if ctr_token.exists():
            self._logger.debug(f"Symlinking {tokfile!s}->{ctr_token!s}")
            tokfile.symlink_to(ctr_token)
            with contextlib.suppress(NotImplementedError):
                tokfile.chmod(0o600, follow_symlinks=False)
            return
        self._logger.debug("Did not find container token file")
        token = get_access_token()
        if token:
            tokfile.touch(mode=0o600)
            tokfile.write_text(token)
            self._logger.debug(f"Created {tokfile}")
        else:
            self._logger.debug("Could not determine access token")

    def _handle_expiry(self, cachefile: Path, expiry: str) -> None:
        try:
            exptime = int(expiry)
        except ValueError:
            self._logger.exception("Could not parse Expires header")
            return
        if time.time() > exptime:
            self._logger.debug(f"Removing expired cache {cachefile!s}")
            try:
                self._remove_astropy_cachedir(cachefile)
            except OSError:
                self._logger.exception(f"Failed to remove cache {cachefile!s}")
                # Having found the parameter, we are done with this url.
                return

    def _remove_astropy_cachedir(self, cachedir: Path) -> None:
        (cachedir / "url").unlink()
        (cachedir / "contents").unlink()
        cachedir.rmdir()

    def _test_for_space(self) -> None:
        cachefile = self._home / ".cache" / "1mb.txt"
        try:
            self._write_a_megabyte(cachefile)
        except OSError as exc:
            self._logger.warning("Could not write 1MB of text")
            self._set_abnormal_startup(exc)
        if self._broken:
            self._try_emergency_cleanup()
            try:
                # Did that clear enough room?
                self._write_a_megabyte(cachefile)
                self._clear_abnormal_startup()
            except OSError:
                pass  # Nope, stay broken.

    def _write_a_megabyte(self, cachefile: Path) -> None:
        # Try to write a 1M block, which should be enough to start the lab.
        sixteen = "0123456789abcdef"
        mega = sixteen * 64 * 1024

        parent = cachefile.parent
        parent.mkdir(exist_ok=True)
        cachefile.write_text(mega)
        self._remove_cachefile(cachefile)

    def _remove_cachefile(self, cachefile: Path) -> None:
        if cachefile.is_file():
            cachefile.unlink()

    def _try_emergency_cleanup(self) -> None:
        # We have either critically low space, or there's something else
        # wrong with the home directory.
        #
        # Try to reclaim the space by removing .cache and .astropy/cache.
        #
        # If we fail here, don't bother with recovery--we will be starting
        # in a degraded mode, and offering the user an explanation, anyway.
        self._logger.warning(
            "Attempting emergency cleanup of .cache and .astropy/cache"
        )
        try:
            for cdir in (
                (self._home / ".cache"),
                (self._home / ".astropy" / "cache"),
            ):
                shutil.rmtree(cdir, ignore_errors=True)
                cdir.mkdir(exist_ok=True)
        except Exception:
            self._logger.exception("Emergency cleanup failed")

    #
    # The third big block is a bunch of file manipulation.
    #
    def _copy_files_to_user_homedir(self) -> None:
        self._logger.debug("Copying files to user home directory")
        self._copy_butler_credentials()
        self._setup_dask()
        self._copy_logging_profile()
        self._copy_dircolors()
        self._copy_etc_skel()

    def _copy_butler_credentials(self) -> None:
        if "AWS_SHARED_CREDENTIALS_FILE" in self._env:
            self._merge_aws_creds()
        if "PGPASSFILE" in self._env:
            self._merge_pgpass()

    def _merge_aws_creds(self) -> None:
        #
        # Merge the config in the original credentials file and the one
        # in our homedir.  For any given section, we assume that the
        # information in the container ("original credentials files")
        # is correct, but leave any other user config alone.
        #
        ascf = "AWS_SHARED_CREDENTIALS_FILE"
        for ev in (ascf, "ORIG_" + ascf):
            if ev not in self._env:
                raise RSPStartupError(RSPErrorCode.EBADENV, None, ev)
        hc_path = Path(self._env["AWS_SHARED_CREDENTIALS_FILE"])
        if not hc_path.parent.exists():
            hc_path.parent.mkdir(mode=0o700, parents=True)
        hc_path.touch(mode=0o600, exist_ok=True)
        home_config = configparser.ConfigParser()
        home_config.read(str(hc_path))
        ro_config = configparser.ConfigParser()
        ro_config.read(self._env["ORIG_AWS_SHARED_CREDENTIALS_FILE"])
        for sect in ro_config.sections():
            home_config[sect] = ro_config[sect]
        with hc_path.open("w") as f:
            home_config.write(f)

    def _merge_pgpass(self) -> None:
        #
        # Same as above, but for pgpass files.
        #
        config = {}
        # Get current config from homedir
        ppf = "PGPASSFILE"
        for ev in (ppf, "ORIG_" + ppf):
            if ev not in self._env:
                raise RSPStartupError(RSPErrorCode.EBADENV)
        home_pgpass = Path(self._env["PGPASSFILE"])
        if not home_pgpass.parent.exists():
            home_pgpass.parent.mkdir(mode=0o700, parents=True)
        home_pgpass.touch(mode=0o600, exist_ok=True)
        lines = home_pgpass.read_text().splitlines()
        for line in lines:
            if ":" not in line:
                continue
            connection, passwd = line.rsplit(":", maxsplit=1)
            config[connection] = passwd.rstrip()
        # Update config from container-supplied one
        ro_pgpass = Path(self._env["ORIG_PGPASSFILE"])
        lines = ro_pgpass.read_text().splitlines()
        for line in lines:
            if ":" not in line:
                continue
            connection, passwd = line.rsplit(":", maxsplit=1)
            config[connection] = passwd.rstrip()
        with home_pgpass.open("w") as f:
            for connection, passwd in config.items():
                f.write(f"{connection}:{passwd}\n")

    def _setup_dask(self) -> None:
        self._logger.debug("Setting up dask dashboard proxy information")
        cfgdir = self._home / ".config" / "dask"
        good_dashboard_config = False
        if cfgdir.is_dir():
            good_dashboard_config = self._tidy_extant_config(cfgdir)
            # If we found and replaced the dashboard config, or if it was
            # already correct, we do not need to write a new file.
            #
            # If there is no config dir, there's nothing to tidy.
        if not good_dashboard_config:
            # We need to write a new file with the correct config.
            self._inject_new_proxy(cfgdir / "dashboard.yaml")

    def _tidy_extant_config(self, cfgdir: Path) -> bool:
        #
        # This is the controversial method.  We have had (at least) four
        # regimes of dask usage in the RSP.
        #
        # 1) Back in the mists of time (2018-ish), dask was present, and
        # all configuration was left to the user.
        # 2) For a while in 2019-2021-ish, we had a pretty sophisticated
        # system that allowed users to spawn whole additional pods, and we used
        # this for a really cool demo with Gaia DR1 data.  But then we moved to
        # the Nublado controller from KubeSpawner, and that no longer worked...
        # but we didn't do anything about the user config, so users had broken
        # config left over.
        # 3) from 2022-ish-to-2025 dask was not present.  The broken config
        # thus didn't cause any harm.
        # 4) in 2025, we added lsdb to the RSP.  lsdb relies on dask.  Suddenly
        # the abandoned config could cause harm, and without config, the wrong
        # dashboard information is presented to the user, which makes the lsdb
        # tutorial for Rubin DP1 data needlessly confusing.
        #
        # This is an attempt to clean that mess up.
        #
        # First we check for any files that don't do anything.  We know the
        # config will be YAML (dask config can also be JSON, but the RSP
        # machinery never wrote any such files, so we assume any JSON is
        # user-generated and not directly our problem), and those files will
        # be named with "yaml" or "yml" suffixes (both exist in extant user
        # config) per https://github.com/dask/dask/blob/main/dask/config.py .
        #
        # "Don't do anything" means that when deserialized to a Python object,
        # that object is None or empty, or it's a dictionary that contains only
        # empty objects as its leaves.  We move these files aside, with a date
        # suffix so that dask will no longer try to load them.
        #
        # Second, assuming the file survived that process, we check
        # specifically for the dashboard link, and correct it from its old,
        # non-user-domain-aware form, to a form that will be correct whether or
        # not user domains are enabled.  We save the original file with a date
        # suffix; again, dask will no longer try to load it.
        #
        # Other settings should stay the same; this may mean that the user has
        # settings for in-cluster kubernetes-driven workers, and those will
        # fail to spawn, but we haven't yet figured out how to safely remove
        # that configuration.
        #
        # If, after doing all of this, at least one file contains the correct
        # dashboard config, return True.  Otherwise, return False.

        retval = False

        for suffix in ("yaml", "yml"):
            files = list(cfgdir.glob(f"*.{suffix}"))
            if files:
                for fl in files:
                    today = (
                        datetime.datetime.now(tz=datetime.UTC)
                        .date()
                        .isoformat()
                    )
                    bk = Path(f"{fl!s}.{today}")
                    newcfg = self._clean_empty_config(fl, bk)
                    if not newcfg:
                        continue  # next file
                    retval = self._fix_dashboard(newcfg, fl, bk)
        return retval

    def _clean_empty_config(self, fl: Path, bk: Path) -> dict[str, Any] | None:
        # returns the deserialized yaml object if 1) it was deserializable
        # in the first place, and 2) it survived flensing.
        try:
            obj = yaml.safe_load(fl.read_text())
        except Exception:
            self._logger.exception(
                f"Failed to deserialize {fl!s} as yaml; moving to {bk}"
            )
            obj = None
        flensed = self._flense_dict(obj) if obj else None
        if not flensed:
            self._logger.warning(
                f"{fl} is empty after flensing; moving to {bk}"
            )
            shutil.move(fl, bk)
            return None
        # It's legal YAML and it's not empty
        return flensed

    def _fix_dashboard(self, cfg: dict[str, Any], fl: Path, bk: Path) -> bool:
        # Look for "distributed.dashboard.link".
        # It may have an older, non-user-domain-aware link in it,
        # and if so, then we need to replace it with the newer,
        # user-domain-aware one.

        # Dask does the template-from-environment substitution so these are
        # just strings.  The point is that "old" is not correct in a
        # user-domain-aware world, but "new" works in either case (and also
        # is something JupyterHub gives us for free, and does not rely on our
        # very-RSP-specific-and-going-away-with-service-discovery
        # EXTERNAL_INSTANCE_URL variable).

        # We return True if the deserialized contents of the file named by fl
        # (which will be passed to us as cfg) is a dashboard config with the
        # new template (whether initially or after correction) and False
        # otherwise.

        old = "{EXTERNAL_INSTANCE_URL}{JUPYTERHUB_SERVICE_PREFIX}"
        new = "{JUPYTERHUB_PUBLIC_URL}"

        try:
            val = cfg["distributed"]["dashboard"]["link"]
            if not isinstance(val, str):
                # Pretty sure this is an error, but leave it as the user's
                # problem.
                self._logger.warning(
                    "distributed.dashboard.link is not a string"
                )
                return False
        except KeyError:
            # We don't have the structure.  This file is not our problem.
            self._logger.debug(
                f"{fl!s} does not contain `distributed.dashboard.link`"
            )
            return False
        if val.find(new) > -1:
            # The structure is there and is already correct.
            # Return True and don't update anything.
            return True
        if val.find(old) < 0:
            # The structure is there but doesn't have the old-style link.
            # Assume, again, that's intentional.
            self._logger.debug(f"{val} does not contain {old}")
            return False

        # At this point, we have found distributed.dashboard.link.
        # It is a string, and it contains the old-style template so we want
        # to copy the original file to something without a yaml/yml suffix,
        # and replace the contents of the file with the old data but the
        # corrected link.
        try:
            # Make a backup.
            shutil.copy2(fl, bk)
        except Exception:
            self._logger.exception(f"Failed to back up {fl!s} to {bk!s}")
            return False
        newval = val.replace(old, new)
        if newval == val:
            self._logger.warning(
                f"Replacing '{old}' with '{new}' in '{val}' had no effect"
            )
            return False
        cfg["distributed"]["dashboard"]["link"] = newval
        self._logger.info(f"Replaced link in {fl!s}: {old}->{new}")
        try:
            fl.write_text(yaml.dump(cfg, default_flow_style=False))
        except Exception:
            self._logger.exception(f"Failed to write '{cfg}' to {fl!s}")
            return False
        return True

    def _inject_new_proxy(self, tgt: Path) -> None:
        # Conventional for RSP.
        parent = tgt.parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except FileExistsError:
            self._logger.exception(
                f"{parent!s} exists and is not a directory; aborting"
            )
            return
        newlink = "{JUPYTERHUB_PUBLIC_URL}proxy/{port}/status"
        goodlink = {"distributed": {"dashboard": {"link": newlink}}}
        if tgt.exists():
            try:
                obj = self._flense_dict(yaml.safe_load(tgt.read_text()))
                if obj is None:
                    obj = {}
                    # We'll turn it into an empty dict and get it in the
                    # update.  Why was there an empty dashboard.yaml?  Weird.
                elif obj == goodlink:
                    # This is the expected case.  There's only one entry in
                    # the target dashboard.yaml, and it's already correct.
                    return
                else:
                    self._logger.warning(
                        f"{tgt!s} exists; contains '{obj}'"
                        f" not just '{goodlink}'"
                    )
                obj.update(goodlink)
            except Exception:
                self._logger.exception(f"Failed to load {tgt!s}")
        else:
            obj = goodlink
        try:
            tgt.write_text(yaml.dump(obj, default_flow_style=False))
        except Exception:
            self._logger.exception(f"Failed to write '{obj}' to {tgt!s}")

    def _flense_dict(
        self, obj: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Recursively walk a dict; any place a null value is found, it
        and its corresponding key are removed.
        """
        if not obj:
            return None
        retval: dict[str, Any] = {}
        for key, val in obj.items():
            if val is None:
                continue
            if not isinstance(val, dict):
                retval[key] = val
                continue
            flensed = self._flense_dict(val)
            if flensed is None:
                continue
            retval[key] = flensed
        return retval if retval else None

    def _copy_logging_profile(self) -> None:
        self._logger.debug("Copying logging profile if needed")
        user_profile = (
            self._home
            / ".ipython"
            / "profile_default"
            / "startup"
            / "20-logging.py"
        )
        #
        # We have a list of previous supplied versions of 20-logging.py.
        #
        # If the one we have has a hash that matches any of those, then
        # there is a new container-supplied 20-logging.py that should replace
        # it.  However, if we have a 20-logging.py that does not match
        # any of those, then it has been locally modified, and we should
        # not replace it.  If we don't have one at all, we need to copy it
        # into place.
        #
        copy = False
        if not user_profile.is_file():
            copy = True  # It doesn't exist, so we need one.
        else:
            user_loghash = hashlib.sha256(
                user_profile.read_bytes()
            ).hexdigest()
            if user_loghash in PREVIOUS_LOGGING_CHECKSUMS:
                self._logger.debug(
                    f"User log profile '{user_loghash}' is"
                    " out-of-date; replacing with current version."
                )
                copy = True
        if copy:
            pdir = user_profile.parent
            if not pdir.is_dir():
                pdir.mkdir(parents=True)
            jl_path = get_jupyterlab_config_dir()
            srcfile = jl_path / "etc" / "20-logging.py"
            # Location changed with two-python container.  Try each.
            if not srcfile.is_file():
                srcfile = jl_path / "20-logging.py"
            if not srcfile.is_file():
                self._logger.warning("Could not find source user log profile.")
                return
            user_profile.write_bytes(srcfile.read_bytes())

    def _copy_dircolors(self) -> None:
        self._logger.debug("Copying dircolors if needed")
        if not (self._home / ".dir_colors").exists():
            self._logger.debug("Copying dircolors")
            dc = ETC_PATH / "dircolors.ansi-universal"
            dc_txt = dc.read_text()
            (self._home / ".dir_colors").write_text(dc_txt)
        else:
            self._logger.debug("Copying dircolors not needed")

    def _copy_etc_skel(self) -> None:
        self._logger.debug("Copying files from /etc/skel if they don't exist")
        etc_skel = ETC_PATH / "skel"
        contents = etc_skel.walk()
        #
        # We assume that if the file exists at all, we should leave it alone.
        # Users are allowed to modify these, after all.
        #
        for entry in contents:
            dirpath = entry[0]
            dirs = [Path(x) for x in entry[1]]
            files = [Path(x) for x in entry[2]]
            # Determine what the destination directory should be
            if dirpath == etc_skel:
                current_dir = self._home
            else:
                current_dir = (
                    self._home / str(dirpath)[(len(str(etc_skel)) + 1) :]
                )
            # For each directory in the tree at this level:
            # if we don't already have one in our directory, make it.
            for d_item in dirs:
                if not (current_dir / d_item).is_dir():
                    (current_dir / d_item).mkdir()
                    self._logger.debug(f"Creating {current_dir / d_item!s}")
            # For each file in the tree at this level:
            # if we don't already have one in our directory, copy the
            # contents.
            for f_item in files:
                if not (current_dir / f_item).exists():
                    src = Path(entry[0] / f_item)
                    self._logger.debug(f"Creating {current_dir / f_item!s}")
                    src_contents = src.read_bytes()
                    (current_dir / f_item).write_bytes(src_contents)

    #
    # Now that we're not checking out notebooks anymore, all we have to do
    # with Git is install git-lfs.
    #
    def _setup_git(self) -> None:
        # Set up Git LFS
        self._setup_gitlfs()

    def _setup_gitlfs(self) -> None:
        # Check for git-lfs
        self._logger.debug("Installing Git LFS if needed")
        if not self._check_for_git_lfs():
            self._cmd.run("git", "lfs", "install")
            self._logger.debug("Git LFS installed")

    def _check_for_git_lfs(self) -> bool:
        gitconfig = self._home / ".gitconfig"
        if gitconfig.is_file():
            gc = gitconfig.read_text().splitlines()
            for line in gc:
                line.strip()
                if line == '[filter "lfs"]':
                    return True
        return False

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

        txt = self._make_abnormal_landing_markdown()
        s_obj = {"defaultViewers": {"markdown": "Markdown Preview"}}
        s_txt = json.dumps(s_obj)

        try:
            temphome = self._env.get("SCRATCH_DIR", "/tmp")
            welcome = Path(temphome) / "notebooks" / "tutorials" / "welcome.md"
            welcome.parent.mkdir(exist_ok=True, parents=True)
            welcome.write_text(txt)
            settings = (
                Path(temphome)
                / ".jupyter"
                / "lab"
                / "user-settings"
                / "@jupyterlab"
                / "docmanager-extension"
                / "plugin.jupyterlab-settings"
            )
            settings.parent.mkdir(exist_ok=True, parents=True)
            settings.write_text(s_txt)
        except Exception:
            self._logger.exception(
                "Writing files to report abnormal startup failed"
            )

    def _make_abnormal_landing_markdown(self) -> str:
        user = self._env["USER"]
        home = self._env.get(
            "NUBLADO_HOME",
            self._env.get(
                "HOME",
                f"/home/{user}",  # Guess, albeit a good one.
            ),
        )

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
                    remove unneeded files in `{home}`.  You can use the
                    `quota` command to check your usage.

                    After that, shut down and restart the lab.  If that does
                    not result in a working lab:
                    """
                )
            case "ENOSPC":
                txt += dedent(
                    f"""
                    You have run out of filesystem space.  Try using the
                    terminal to remove unneeded files in `{home}`.  Since the
                    filesystem is full, this may not be something you can
                    correct.

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
            val = self._env.get(envvar, "")
            if val:
                result.append(f"--{setting}={val}")
        return result

    def _write_lab_startup_files(self) -> None:
        if self._broken:
            self._logger.warning(
                f"Abnormal startup: {self._env['ABNORMAL_STARTUP_MESSAGE']}"
            )
            self._make_abnormal_startup_environment()
            #
            # We will check to see if we got SCRATCH_DIR set before we broke,
            # and if so, use that, which would be a user-specific path on a
            # scratch filesystem.  If we didn't, we just use "/tmp" and hope
            # for the best.  Any reasonably-configured RSP running under K8s
            # will not have a shared "/tmp".
            #
            temphome = self._env.get("SCRATCH_DIR", "/tmp")
            self._logger.warning(f"Launching with homedir='{temphome}'")
            self._env["HOME"] = temphome
            self._home = Path(temphome)
        # Used by shell startup inside the Lab.
        self._env["RUNNING_INSIDE_JUPYTERLAB"] = "TRUE"
        # If any of these fails, lsst.rsp.startup ought to react to the
        # lack of the appropriate files and start in degraded mode with
        # an explanation.
        try:
            self._write_noninteractive_command()
            self._write_lab_environment()
            self._write_lab_args()
        except Exception:
            self._logger.exception("Writing Lab startup files failed")

    def _write_noninteractive_command(self) -> None:
        # Only write "noninteractive.json" if we are running in
        # non-interactive mode.
        if not bool(self._env.get("NONINTERACTIVE", "")):
            return
        config_path = (
            get_runtime_mounts_dir()
            / "noninteractive"
            / "command"
            / "command.json"
        )
        noninteractive_cmd_file = STARTUP_PATH / "noninteractive.json"
        noninteractive_cmd_file.write_text(config_path.read_text())

    def _write_lab_environment(self) -> None:
        persistent_env = {
            x: self._env[x]
            for x in self._env
            if x in RUNTIME_ENVIRONMENT_VARIABLES and self._env[x]
        }
        env_file = STARTUP_PATH / "env.json"
        env_file.write_text(json.dumps(persistent_env))

    def _write_lab_args(self) -> None:
        log_level = "DEBUG" if self._debug else "INFO"
        notebook_dir = f"{self._home!s}"
        args_file = STARTUP_PATH / "args.json"
        # Make a new list from the static args and our own info.
        cmd_args = list(LAB_STATIC_CMD_ARGS)
        cmd_args.append(f"--notebook-dir={notebook_dir}")
        cmd_args.append(f"--log-level={log_level}")
        cmd_args.extend(self._set_timeout_variables())
        args_file.write_text(json.dumps(cmd_args))
