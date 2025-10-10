"""nox configuration for the Nublado client."""

from __future__ import annotations

import nox
from nox_uv import session

# Default sessions.
nox.options.sessions = ["typing", "test", "coverage-report"]

# Other nox defaults.
nox.options.default_venv_backend = "uv"
nox.options.reuse_existing_virtualenvs = True


@session(name="coverage-report", uv_groups=["dev"])
def coverage_report(session: nox.Session) -> None:
    """Generate a code coverage report from the test suite."""
    session.run("coverage", "report", *session.posargs)


@session(uv_groups=["dev"])
def test(session: nox.Session) -> None:
    """Test both the server and the client."""
    session.run(
        "pytest",
        "--cov=rubin.nublado.client",
        "--cov-branch",
        "--cov-report=",
        *session.posargs,
    )


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
