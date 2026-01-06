"""Manage merging site Butler credentials with user-specific credentials."""

import configparser
from pathlib import Path

from structlog.stdlib import BoundLogger

from ..exceptions import RSPErrorCode, RSPStartupError

__all__ = ["CredentialManager"]


class CredentialManager:
    """Merge site credentials with user-specific credentials."""

    def __init__(self, env: dict[str, str], logger: BoundLogger) -> None:
        self._env = env
        self._logger = logger

    def copy_butler_credentials(self) -> None:
        """Merge site Butler credentials with user-specific ones.

        Raises
        ------
        RSPStartupError
            Raised if credentials are missing from user config.
        OSError
            Raised if file manipulation fails somehow.
        """
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
        self._logger.debug("Merged site AWS creds with user creds.")

    def _merge_pgpass(self) -> None:
        #
        # Same as above, but for pgpass files.
        #
        config = {}
        # Get current config from homedir
        ppf = "PGPASSFILE"
        for ev in (ppf, "ORIG_" + ppf):
            if ev not in self._env:
                raise RSPStartupError(RSPErrorCode.EBADENV, None, ev)
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
        self._logger.debug("Merged site Postgres creds with user creds.")
