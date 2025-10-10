"""nox build configuration for Nublado."""

import shutil
import sys
from collections import defaultdict
from pathlib import Path

import nox
from nox.command import CommandFailed
from nox_uv import session

# Default sessions
nox.options.sessions = ["lint", "typing", "test", "converage-report", "docs"]

# Other nox defaults
nox.options.default_venv_backend = "uv"
nox.options.reuse_existing_virtualenvs = True

# Recurse into these subdirectories, which have their own separate noxfile.py.
_SUBDIRECTORIES = ["client", "controller", "hub"]


@session(name="coverage-report", requires=["test"], uv_groups=["dev", "nox"])
def coverage_report(session: nox.Session) -> None:
    """Generate a code coverage report from the test suite."""
    session.run("coverage", "report", *session.posargs)
    for subdir in _SUBDIRECTORIES:
        with session.chdir(subdir):
            session.run("nox", "-s", "coverage-report", "--", *session.posargs)


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


@session(uv_groups=["dev", "nox"])
def test(session: nox.Session) -> None:
    """Run tests."""
    # If the user passed in arguments to the session, they may be specific
    # tests to run. In that case, only run tests in the relevant directory.
    # This requires some unfortunately complicated argument parsing to
    # separate out the generic arguments, any tests specific to the parent
    # directory, and any tests specific to subdirectories.
    generic = []
    per_directory: dict[str, list[str]] = defaultdict(list)
    parent_tests = []
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
                        per_directory[subdir].append(arg.removeprefix(prefix))
                        found = True
                        break
                if not found:
                    generic.append(arg)
        else:
            generic.append(arg)

    # Whether any specific tests were specified.
    any_tests = any(parent_tests + list(per_directory.values()))

    # Run in the parent dir if a parent dir test was specified, or if no tests
    # were specified.
    if parent_tests or not any_tests:
        session.run(
            "pytest",
            "--cov=rubin.nublado.purger",
            "--cov=rubin.nublado.inithome",
            "--cov-branch",
            "--cov-report=",
            *generic,
            *parent_tests,
        )

    # Run in a subdirectory if a test in that subdirectory was specified, or
    # if no tests were specified.
    for subdir in _SUBDIRECTORIES:
        subdir_tests = per_directory[subdir]
        if subdir_tests or not any_tests:
            with session.chdir(subdir):
                session.run("nox", "-s", "test", "--", *generic, *subdir_tests)


@session(uv_groups=["dev", "nox", "typing"])
def typing(session: nox.Session) -> None:
    """Run mypy."""
    session.run(
        "mypy",
        *session.posargs,
        "--namespace-packages",
        "--explicit-package-bases",
        "noxfile.py",
        "inithome/src",
        "purger/src",
        "tests",
        env={"MYPYPATH": "inithome/src:purger/src"},
    )
    for subdir in _SUBDIRECTORIES:
        with session.chdir(subdir):
            session.run("nox", "-s", "typing", "--", *session.posargs)
