"""nox build configuration for Nublado."""

import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import nox
from nox.command import CommandFailed
from nox_uv import session

# Default sessions
nox.options.sessions = ["lint", "typing", "test", "coverage-report", "docs"]

# Other nox defaults
nox.options.default_venv_backend = "uv"
nox.options.reuse_existing_virtualenvs = True

# Recurse into these subdirectories, which have their own separate noxfile.py.
_SUBDIRECTORIES = ["client", "hub"]


def _recurse(session: nox.Session, target: str) -> None:
    """Recurse into all subdirectories and run the target there."""
    for subdir in _SUBDIRECTORIES:
        with session.chdir(subdir):
            session.run("nox", "-s", target, "--", *session.posargs)


@session(name="coverage-report", requires=["test"], uv_groups=["dev", "nox"])
def coverage_report(session: nox.Session) -> None:
    """Generate a code coverage report from the test suite."""
    session.run("coverage", "report", *session.posargs)
    _recurse(session, "coverage-report")


@session(uv_groups=["dev", "docs"])
def docs(session: nox.Session) -> None:
    """Build the documentation."""
    doctree_dir = (session.cache_dir / "doctrees").absolute()
    with session.chdir("docs"):
        session.run(
            "sphinx-build",
            "-W",
            "--keep-going",
            "-n",
            "-T",
            "-b",
            "html",
            "-d",
            str(doctree_dir),
            ".",
            "./_build/html",
        )


@session(name="docs-clean", uv_groups=["dev", "docs"])
def docs_clean(session: nox.Session) -> None:
    """Build the documentation without any cache."""
    if Path("docs/_build").exists():
        shutil.rmtree("docs/_build")
    if Path("docs/dev/api/contents").exists():
        shutil.rmtree("docs/dev/api/contents")
    docs(session)


@session(name="docs-linkcheck", uv_groups=["dev", "docs"])
def docs_linkcheck(session: nox.Session) -> None:
    """Check links in the documentation."""
    doctree_dir = (session.cache_dir / "doctrees").absolute()
    with session.chdir("docs"):
        try:
            session.run(
                "sphinx-build",
                "-W",
                "--keep-going",
                "-n",
                "-T",
                "-b",
                "linkcheck",
                "-d",
                str(doctree_dir),
                ".",
                "./_build/linkcheck",
            )
        except CommandFailed:
            output_path = Path("_build") / "linkcheck" / "output.txt"
            if output_path.exists():
                sys.stdout.write(output_path.read_text())
            session.error("Link check reported errors")


@session(uv_only_groups=["lint"], uv_no_install_project=True)
def lint(session: nox.Session) -> None:
    """Run pre-commit hooks."""
    session.run("pre-commit", "run", "--all-files", *session.posargs)


@dataclass
class TestArguments:
    """Holds parsed test arguments, used to control test recursion.

    If the user passed in arguments to the session, they may be specific tests
    to run. In that case, only run tests in the relevant directory. This
    requires some unfortunately complicated argument parsing to separate out
    the generic arguments, any tests specific to the parent directory, and any
    tests specific to subdirectories. This class handles that parsing.
    """

    generic: list[str]
    """Arguments that don't limit execution and are always used."""

    per_directory: dict[str, list[str]]
    """Arguments that apply to only one subdirectory."""

    parent_tests: list[str]
    """Specific tests to run only in the parent directory."""

    @classmethod
    def from_session(cls, session: nox.Session) -> Self:
        """Parse the session arguments into this data structure."""
        generic = []
        per_directory: dict[str, list[str]] = defaultdict(list)
        parent_tests = []

        # Parse the session arguments.
        for arg in session.posargs:
            # Ignore a speficied test when testing if the file exists.
            test_file = arg.split("::")[0]
            if "tests/" in arg and Path(test_file).exists():
                if arg.startswith("tests/"):
                    parent_tests.append(arg)
                else:
                    found = False
                    for subdir in _SUBDIRECTORIES:
                        prefix = f"{subdir}/"
                        if arg.startswith(f"{prefix}tests"):
                            adjusted_arg = arg.removeprefix(prefix)
                            per_directory[subdir].append(adjusted_arg)
                            found = True
                            break
                    if not found:
                        generic.append(arg)
            else:
                generic.append(arg)

        # Return the results.
        return cls(
            generic=generic,
            per_directory=per_directory,
            parent_tests=parent_tests,
        )

    @property
    def run_all_tests(self) -> bool:
        """Return whether all tests are being run."""
        return not any(self.parent_tests + list(self.per_directory.values()))


@session(uv_groups=["dev", "nox"])
def test(session: nox.Session) -> None:
    """Run tests."""
    args = TestArguments.from_session(session)

    # Run in the parent dir if a parent dir test was specified, or if no tests
    # were specified.
    if args.parent_tests or args.run_all_tests:
        session.run(
            "pytest",
            "--cov=nublado",
            "--cov-branch",
            "--cov-report=",
            *args.generic,
            *args.parent_tests,
        )

    # Run in a subdirectory if a test in that subdirectory was specified, or
    # if no tests were specified.
    for subdir in _SUBDIRECTORIES:
        subdir_tests = args.per_directory[subdir]
        if subdir_tests or args.run_all_tests:
            with session.chdir(subdir):
                session.run(
                    "nox", "-s", "test", "--", *args.generic, *subdir_tests
                )


@session(uv_groups=["dev", "nox", "typing"])
def typing(session: nox.Session) -> None:
    """Run mypy."""
    session.run(
        "mypy",
        *session.posargs,
        "--namespace-packages",
        "--explicit-package-bases",
        "noxfile.py",
        "tests",
    )
    _recurse(session, "typing")
