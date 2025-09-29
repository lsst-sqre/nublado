"""nox build configuration for Nublado."""

import shutil
import sys
from collections import defaultdict
from pathlib import Path

import nox
from nox.command import CommandFailed
from nox_uv import session

# Default sessions
nox.options.sessions = ["lint", "typing", "test", "docs"]

# Other nox defaults
nox.options.default_venv_backend = "uv"
nox.options.reuse_existing_virtualenvs = True

# Recurse into these subdirectories, which have their own separate noxfile.py.
_SUBDIRECTORIES = ["client", "controller", "hub"]


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
    parent = []
    found_parent = False
    for arg in session.posargs:
        if "tests/" in arg and Path(arg).exists():
            if arg.startswith("tests/"):
                parent.append(arg)
                found_parent = True
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
    found_parent = found_parent or not per_directory
    if not per_directory:
        per_directory = {s: [] for s in _SUBDIRECTORIES}

    # found_parent now says whether to run tests in the parent directory,
    # which is true if a test from the parent directory was specified or if
    # there were no tests from subdirectories specified. per_directory has a
    # mapping of directories to tests to run.
    if found_parent:
        session.run("pytest", *generic, *parent)
    for subdir, args in per_directory.items():
        with session.chdir(subdir):
            session.run("nox", "-s", "test", "--", *generic, *args)


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
