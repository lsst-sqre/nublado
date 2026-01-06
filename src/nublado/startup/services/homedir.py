"""Tasks around ensuring the home directory is working correctly."""

import contextlib
import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse

from structlog.stdlib import BoundLogger

from ..constants import (
    ETC_PATH,
    MAX_NUMBER_OUTPUTS,
    PREVIOUS_LOGGING_CHECKSUMS,
)
from ..storage.command import Command
from ..utils import (
    get_access_token,
    get_jupyterlab_config_dir,
    get_runtime_mounts_dir,
)
from .credentials import CredentialManager
from .dask import DaskConfigurator

__all__ = ["HomedirManager"]


class HomedirManager:
    """Ensure homedir is working correctly."""

    def __init__(
        self, env: dict[str, str], home: Path, logger: BoundLogger
    ) -> None:
        self._env = env
        self._logger = logger
        self._home = home
        self._cmd = Command(ignore_fail=True)

    def tidy_homedir(self) -> None:
        """Clean up stale cache."""
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
                self._logger.exception(f"Could not read {urlfile!s}")
                continue
            qry = urlparse(url).query
            if not qry:
                continue
            for key, value in parse_qsl(qry):
                if key.lower() == "expires":
                    self._handle_expiry(c, value)

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
        except OSError:
            self._logger.warning("Could not write 1MB of text")
            self._try_emergency_cleanup()
            try:
                # Did that clear enough room?
                self._write_a_megabyte(cachefile)
                # Succeeded?  We're OK, then.
            except Exception:
                self._logger.exception("Cleanup failed")
            else:
                return
            raise

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

    def copy_files_to_user_homedir(self) -> None:
        """Copy files from read-only container into user home.

        Raises
        ------
        OSError
            Raised if something goes wrong during a file copy.
        """
        self._logger.debug("Copying files to user home directory")
        cred_mgr = CredentialManager(env=self._env, logger=self._logger)
        cred_mgr.copy_butler_credentials()
        dask_mgr = DaskConfigurator(home=self._home, logger=self._logger)
        dask_mgr.setup_dask()
        self._setup_gitlfs()
        self._copy_logging_profile()
        self._copy_dircolors()
        self._copy_etc_skel()

    def modify_interactive_settings(self) -> None:
        """Change those (on-disk) settings used for interactive Lab startup.

        Raises
        ------
        OSError
            Raised if some file manipulation fails.  Caught in the preparer.
        """
        self._logger.debug("Modifying interactive settings if needed")
        # These both write files; if either fails, start up but warn
        # the user their experience is likely to be bad.
        self._manage_access_token()
        self._increase_log_limit()

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
                if line.strip() == '[filter "lfs"]':
                    return True
        return False

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
