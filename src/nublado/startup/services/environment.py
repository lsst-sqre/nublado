"""Handles updates to the runtime environment."""

import asyncio
import os
from pathlib import Path

from rubin.repertoire import DiscoveryClient, RepertoireError
from structlog.stdlib import BoundLogger

from ..utils import get_digest

__all__ = ["EnvironmentConfigurator"]


class EnvironmentConfigurator:
    """Set up runtime environment for the Lab."""

    def __init__(self, env: dict[str, str], logger: BoundLogger) -> None:
        self._env = env
        self._logger = logger
        # We know $HOME is set before we ever get here.
        self._home = Path(self._env["HOME"])

    def configure_env(self) -> dict[str, str]:
        """Set runtime environment variables used by Lab.

        Returns
        -------
        dict[str,str]
            Updated runtime environment
        """
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
        return self._env

    def _set_user(self) -> None:
        self._logger.debug("Determining user name from home directory")
        self._env["USER"] = self._home.name

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
        # Set up discovery client.  Only used right here for now.
        ext_url = self._env.get(
            "EXTERNAL_INSTANCE_URL", "https://localhost:8888"
        )
        rep_url = self._env.get("REPERTOIRE_BASE_URL", ext_url + "/repertoire")
        discovery = DiscoveryClient(base_url=rep_url)
        emsg = "Discovery of portal service failed; not setting variables"
        try:
            ff_url = await discovery.url_for_ui("portal")
        except RepertoireError:
            self._logger.exception(emsg)
            return
        finally:
            await discovery.aclose()  # Done with discovery client.
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
