"""A tool to set up user directories to hold what will be the default
page for "science" sites, to allow those sites to load a tutorial
document on startup.

It has two phases: first, it creates links to the landing page and the
files that page needs, and second, if the user default for opening the
file is not the Markdown Viewer already, it writes out configuration
for that.

The links need to be somewhere the lab container documentManager can
access then, therefore inside the homedir and not hidden dot files.

It is expected to be running in the context of the current user, as
part of an initContainer running after the user home directories are
provisioned, but before the user lab container begins to start.
"""

import json
from typing import Any, Self

from .exceptions import (
    DestinationError,
    DestinationIsDirectoryError,
    PrecheckError,
)
from .input import ProvisionerInput, input_from_env


class Provisioner:
    """Ensure user environment is ready to open tutorial landing page.

    Parameters
    ----------
    inp
        Input document specifying document source, user home, destination
        directory, and whether to enable debugging.
    """

    def __init__(self, inp: ProvisionerInput) -> None:
        self._debug = inp.debug
        self._source_files = inp.source_files
        self._home_dir = inp.home_dir
        self._dest_dir = inp.dest_dir

    def _precheck(self) -> None:
        for sf in self._source_files:
            if not sf.is_file():
                raise PrecheckError(f"Source file {sf} is not a file")
        if not self._home_dir.is_dir():
            raise PrecheckError(
                "Home directory {self._home_dir} is not a directory"
            )

    def _provision_tutorial_directories(self) -> None:
        t_dir = self._dest_dir / "notebooks" / "tutorials"
        t_dir.mkdir(mode=0o755, exist_ok=True, parents=True)

    def _link_files(self) -> None:
        for src in self._source_files:
            dest = self._dest_dir / src.name
            if dest.exists(follow_symlinks=False):
                if dest.is_dir():
                    raise DestinationIsDirectoryError(str(dest))
                if dest.is_file():
                    # Remediation from a past attempt.  If it's a file,
                    # it shouldn't be, it should be a symlink.  Remove
                    # and recreate.
                    dest.unlink()
                elif dest.is_symlink():
                    current_target = dest.readlink()
                    if current_target != src:
                        dest.unlink()
                else:
                    # It's...a device, or a named pipe, or ... something?
                    raise DestinationError(str(dest))
            # If we get here and it still exists, it's a symlink pointing
            # to the right target, so we just leave it alone.
            if not dest.exists(follow_symlinks=False):
                dest.symlink_to(src)

    def _edit_settings(self) -> None:
        settings_dir = (
            self._home_dir
            / ".jupyter"
            / "lab"
            / "user-settings"
            / "@jupyterlab"
            / "docmanager-extension"
        )
        settings_dir.mkdir(exist_ok=True, parents=True)
        settings_file = settings_dir / "plugin.jupyterlab-settings"
        settings: dict[str, Any] = {}
        write = False
        if settings_file.exists():
            # It's supposed to be a JSON doc.
            settings = json.loads(settings_file.read_text())
        if "defaultViewers" not in settings:
            settings["defaultViewers"] = {}
        if "markdown" not in settings["defaultViewers"]:
            # If the user set it to something else, leave it alone.
            settings["defaultViewers"]["markdown"] = "Markdown Preview"
            write = True
        if write:
            settings_file.write_text(
                json.dumps(settings, sort_keys=True, indent=2)
            )

    def go(self) -> None:
        """Do the deed."""
        self._precheck()
        self._provision_tutorial_directories()
        self._link_files()
        self._edit_settings()

    @classmethod
    def from_env(cls) -> Self:
        """Create provisioner from environment."""
        inp = input_from_env()
        return cls(inp)
