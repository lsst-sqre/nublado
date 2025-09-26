"""nox configuration for the Nublado client."""

from __future__ import annotations

import nox
from nox_uv import session

# Default sessions.
nox.options.sessions = ["typing", "test"]

# Other nox defaults.
nox.options.default_venv_backend = "uv"
nox.options.reuse_existing_virtualenvs = True


@session(uv_groups=["dev"])
def test(session: nox.Session) -> None:
    """Test both the server and the client."""
    session.run("pytest", *session.posargs)


@session(uv_groups=["dev", "typing"])
def typing(session: nox.Session) -> None:
    """Run mypy."""
    session.run(
        "mypy",
        *session.posargs,
        "--namespace-packages",
        "--explicit-package-bases",
        "noxfile.py",
        "src",
        "tests",
        env={"MYPYPATH": "src"},
    )
